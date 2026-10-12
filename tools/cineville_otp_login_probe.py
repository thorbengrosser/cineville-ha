#!/usr/bin/env python3
"""Probe: can Home Assistant do the Cineville login itself (email -> emailed code -> tokens)?

Walks through Cineville's own login pages with a private cookie session, the way the integration would:
  1. open the authorize URL (app client, PKCE, response_mode=form_post) -> email form
  2. submit the email address -> Cineville emails a one-time code -> code form
  3. submit the code -> the form_post page with the OAuth `code` -> exchange it for tokens
Then reads the watchlist size and revokes the login again.

The output is safe to share: page paths without query values, form field names and types, HTTP statuses.
It never prints the email address, the one-time code, the OAuth code or tokens.
Usage: python3 tools/cineville_otp_login_probe.py     (stdlib only)
"""

import base64
import getpass
import hashlib
import http.cookiejar
import json
import os
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

ISSUER = "https://api.cineville.de"
CLIENT_ID = "0d6499ff-c493-4647-8ea3-72cf7543c369"
REDIRECT_URI = "cineville://login-callback"
SCOPE = "openid api offline_access profile email"
UA = "Mozilla/5.0 (X11; Linux x86_64) cineville-ha login probe"


class Forms(HTMLParser):
    """Collects <form>s with their inputs, plus visible text (for error messages)."""

    def __init__(self) -> None:
        super().__init__()
        self.forms: list[dict] = []
        self.text: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style"):
            self._skip += 1
        elif tag == "form":
            self.forms.append({"action": a.get("action") or "", "method": (a.get("method") or "get").lower(), "inputs": []})
        elif tag in ("input", "button", "select", "textarea") and self.forms:
            self.forms[-1]["inputs"].append({
                "tag": tag, "name": a.get("name"), "type": (a.get("type") or "").lower(), "value": a.get("value") or "",
                "autocomplete": a.get("autocomplete"), "inputmode": a.get("inputmode"), "maxlength": a.get("maxlength"),
            })

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip and data.strip():
            self.text.append(data.strip())


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def path_only(url: str) -> str:
    p = urllib.parse.urlparse(url)
    keys = sorted(urllib.parse.parse_qs(p.query).keys())
    return f"{p.netloc}{p.path}" + (f"  (query keys: {', '.join(keys)})" if keys else "")


def show(step: str, url: str, status: int, page: Forms) -> None:
    print(f"\n[{step}] HTTP {status} at {path_only(url)}")
    for i, form in enumerate(page.forms):
        action = path_only(urllib.parse.urljoin(url, form["action"])) if form["action"] else "(same page)"
        print(f"  form {i}: method={form['method']} action={action}")
        for inp in form["inputs"]:
            extra = {k: inp[k] for k in ("autocomplete", "inputmode", "maxlength") if inp[k]}
            print(f"    <{inp['tag']}> name={inp['name']!r} type={inp['type']!r}" + (f" {extra}" if extra else ""))
    if not page.forms:
        print("  (no forms on this page)")


class Session:
    def __init__(self) -> None:
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def request(self, url: str, data: dict | None = None) -> tuple[str, int, str]:
        body = urllib.parse.urlencode(data).encode() if data is not None else None
        req = urllib.request.Request(url, data=body, headers={"User-Agent": UA, "Accept": "text/html,application/json"})
        try:
            with self.opener.open(req, timeout=30) as resp:
                return resp.geturl(), resp.status, resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as err:
            return err.geturl(), err.code, err.read().decode("utf-8", "replace")


def parse(html: str) -> Forms:
    page = Forms()
    page.feed(html)
    return page


def submit(session: Session, url: str, form: dict, values: dict) -> tuple[str, int, str]:
    fields = {i["name"]: i["value"] for i in form["inputs"] if i["name"] and i["type"] in ("hidden", "")}
    fields.update(values)
    target = urllib.parse.urljoin(url, form["action"]) if form["action"] else url
    return session.request(target, fields)


def user_fields(form: dict) -> list[dict]:
    return [i for i in form["inputs"] if i["tag"] == "input" and i["name"] and i["type"] not in ("hidden", "submit", "button", "checkbox")]


def main() -> int:
    verifier = b64url(os.urandom(48))
    state = secrets.token_urlsafe(16)
    authorize = ISSUER + "/connect/authorize?" + urllib.parse.urlencode({
        "response_type": "code", "response_mode": "form_post", "client_id": CLIENT_ID, "redirect_uri": REDIRECT_URI,
        "scope": SCOPE, "code_challenge": b64url(hashlib.sha256(verifier.encode()).digest()),
        "code_challenge_method": "S256", "state": state, "ui_locales": "de-DE",
    })
    s = Session()

    # 1. Email form
    url, status, html = s.request(authorize)
    page = parse(html)
    show("1 login page", url, status, page)
    email_form = next((f for f in page.forms if any(i["type"] == "email" or "mail" in (i["name"] or "").lower() for i in f["inputs"])), None)
    if not email_form:
        print("No email form found; stopping.")
        return 1
    email_field = next(i["name"] for i in user_fields(email_form))
    email = input("\nYour Cineville email address (only sent to Cineville; the script's output never includes it): ").strip()

    # 2. Submit email -> code form
    url, status, html = submit(s, url, email_form, {email_field: email})
    page = parse(html)
    show("2 after submitting the email", url, status, page)
    code_form = next((f for f in page.forms if user_fields(f)), None)
    if not code_form:
        print("  visible text:", " | ".join(page.text[:12]))
        print("No code form found; stopping.")
        return 1
    fields = user_fields(code_form)
    print(f"  -> code entry has {len(fields)} field(s): {[f['name'] for f in fields]}")

    # 3. Submit the emailed one-time code
    otp = getpass.getpass("\nThe code from Cineville's email (hidden while typing): ").strip()
    if len(fields) == 1:
        values = {fields[0]["name"]: otp}
    else:  # one box per digit
        values = {f["name"]: ch for f, ch in zip(fields, otp)}
    url, status, html = submit(s, url, code_form, values)
    page = parse(html)
    show("3 after submitting the code", url, status, page)

    # 4. The form_post page carries the OAuth code
    post = next((f for f in page.forms if any(i["name"] == "code" for i in f["inputs"])), None)
    if not post:
        print("  visible text:", " | ".join(page.text[:12]))
        print("No OAuth code on this page; stopping (wrong code? or the flow differs).")
        return 1
    values = {i["name"]: i["value"] for i in post["inputs"] if i["name"]}
    print(f"  form_post target: {post['action']!r}, state matches: {values.get('state') == state}")

    token_url = ISSUER + "/connect/token"
    _, status, body = Session().request(token_url, {
        "grant_type": "authorization_code", "client_id": CLIENT_ID, "code": values["code"],
        "redirect_uri": REDIRECT_URI, "code_verifier": verifier,
    })
    tokens = json.loads(body) if body.startswith("{") else {}
    print(f"\n[4 token exchange] HTTP {status}, fields: {sorted(tokens)}")
    if "access_token" not in tokens:
        return 1

    def api(path: str) -> dict:
        req = urllib.request.Request(ISSUER + path, headers={"Authorization": f"Bearer {tokens['access_token']}", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())

    user = api("/connect/userinfo")
    watchlist = api(f"/users/{user['sub']}/watchlist/production-ids")["productionIds"]
    print(f"[5 api] logged in as {user.get('given_name') or '(no first name)'}; watchlist has {len(watchlist)} films")

    _, status, _ = Session().request(ISSUER + "/connect/revocation", {
        "client_id": CLIENT_ID, "token": tokens["refresh_token"], "token_type_hint": "refresh_token",
    })
    print(f"[6 revoke] HTTP {status}")
    print("\nAll good: Home Assistant can do this login itself.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
