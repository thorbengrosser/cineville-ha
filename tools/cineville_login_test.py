#!/usr/bin/env python3
"""Prototype of the Home Assistant login flow for Cineville (stdlib only).

Uses the Cineville mobile app's public OAuth client (authorization code + PKCE,
no client secret) and checks that:
  1. the login code can be exchanged for tokens without a secret,
  2. the refresh token renews the access token,
  3. the new token can read the watchlist and the seen-films list,
then revokes the refresh token so no extra session stays behind.

Usage:
  python3 tools/cineville_login_test.py              # code comes back as a page you can read
  python3 tools/cineville_login_test.py --redirect   # classic redirect to cineville://login-callback?code=...
Tokens are only held in memory and never printed.
"""
import base64
import hashlib
import json
import os
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request

ISSUER = "https://api.cineville.de"
CLIENT_ID = "0d6499ff-c493-4647-8ea3-72cf7543c369"  # appAuthClientId for DE, from https://cineville.de/api/tenants
REDIRECT_URI = "cineville://login-callback"
SCOPE = "openid api offline_access profile email"


def b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def post_form(path, fields):
    req = urllib.request.Request(
        ISSUER + path,
        data=urllib.parse.urlencode(fields).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read()
            return resp.status, (json.loads(body) if body else {})
    except urllib.error.HTTPError as err:
        body = err.read()
        try:
            return err.code, json.loads(body)
        except ValueError:
            return err.code, {"raw": body.decode(errors="replace")[:200]}


def get_json(path, token):
    req = urllib.request.Request(ISSUER + path, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def step(name, ok, detail=""):
    print(f"{'ok  ' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
    if not ok:
        sys.exit(1)


def main():
    verifier = b64url(os.urandom(48))
    challenge = b64url(hashlib.sha256(verifier.encode()).digest())
    state = secrets.token_urlsafe(16)
    form_post = "--redirect" not in sys.argv
    query = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        "ui_locales": "de-DE",
    }
    if form_post:
        query["response_mode"] = "form_post"
    url = ISSUER + "/connect/authorize?" + urllib.parse.urlencode(query)

    print("1. Open DevTools first (F12), then open this URL in the same tab and log in (email + one-time code):\n")
    print(url)
    if form_post:
        print("""
2. After the code step the page goes blank or shows an error. That's expected: it tries to
   hand the code to the (missing) app. The code is on that page:
   DevTools -> Elements (Chrome) / Inspector (Firefox) -> search (Ctrl+F) for  name="code"
   -> copy the value="..." of that <input>. If the Elements view is empty, check the Network tab
   instead: the request to /connect/authorize/callback -> Response tab.
""")
    else:
        print("""
2. At the end the browser tries to open cineville://login-callback?code=...
   DevTools -> Network (enable "Preserve log") -> the request to /connect/authorize/callback
   -> response header "Location".
""")
    for attempt in range(3):
        pasted = input("3. Paste the code (or the whole cineville://login-callback?... URL): ").strip()
        if pasted.startswith("cineville:"):
            params = urllib.parse.parse_qs(urllib.parse.urlparse(pasted).query)
            code = params.get("code", [None])[0]
            step("state matches", params.get("state", [None])[0] == state)
        else:
            code = pasted
        step("got a code", bool(code))

        status, tok = post_form("/connect/token", {
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        })
        if status == 200 or tok.get("error") != "invalid_grant" or attempt == 2:
            break
        print(f"      invalid_grant: {tok.get('error_description', 'no description')}")
        print("      The code is expired, already used, or from another run. Reload the blank page")
        print("      (it was requested with THIS run's link) or open the link above again, and paste the new code.\n")
    if tok.get("error") == "invalid_client":
        print("      -> the client requires a secret: not usable from Home Assistant")
    step("code exchange without client secret", status == 200,
         f"HTTP {status} {tok.get('error', '')} {tok.get('error_description', '')}".strip())
    step("response has a refresh token", "refresh_token" in tok, f"fields: {sorted(tok)}")
    print(f"      access token lifetime: {tok.get('expires_in')} s, scope: {tok.get('scope')}")

    status, tok2 = post_form("/connect/token", {
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "refresh_token": tok["refresh_token"],
    })
    step("refresh grant renews the access token", status == 200, f"HTTP {status} {tok2.get('error', '')}")
    rotated = tok2.get("refresh_token") and tok2["refresh_token"] != tok["refresh_token"]
    print(f"      refresh token rotated on use: {bool(rotated)}")
    refresh = tok2.get("refresh_token", tok["refresh_token"])
    access = tok2["access_token"]

    user_id = get_json("/connect/userinfo", access)["sub"]
    watchlist = get_json(f"/users/{user_id}/watchlist/production-ids", access)["productionIds"]
    seen = get_json(f"/users/{user_id}/visit-history/production-ids", access)["productionIds"]
    step("read watchlist", True, f"{len(watchlist)} films")
    step("read seen films", True, f"{len(seen)} films")

    status, _ = post_form("/connect/revocation", {
        "client_id": CLIENT_ID,
        "token": refresh,
        "token_type_hint": "refresh_token",
    })
    step("refresh token revoked", status == 200, f"HTTP {status}")
    print("\nAll good: this login flow works for Home Assistant.")


if __name__ == "__main__":
    main()
