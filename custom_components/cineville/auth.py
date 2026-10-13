"""OAuth login for Cineville member features (watchlist, seen films).

Uses the mobile app's public client: authorization code + PKCE, no client secret. Two ways to get the code:

- OtpLogin (default): Home Assistant fills in Cineville's own login pages: email address -> Cineville emails a
  one-time code -> the user types it into HA -> the form_post page carries the OAuth code.
- Manual fallback: the user opens the authorize URL in a browser and pastes the code from the blank
  form_post page (Home Assistant can't receive the cineville:// redirect).

See docs/api/authentication.md.
"""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

import aiohttp

from .const import API_URL, APP_CLIENT_ID, OAUTH_SCOPE, REDIRECT_URI
from .exceptions import (
    CinevilleAuthError,
    CinevilleConnectionError,
    CinevilleError,
    CinevilleLoginPageError,
    CinevilleNoAccountError,
    CinevilleOtpError,
)

# Refresh the access token this many seconds before it expires
REFRESH_MARGIN = 120


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


@dataclass(frozen=True, slots=True)
class LoginRequest:
    """One login attempt. The verifier must be kept until the code is exchanged."""

    authorize_url: str
    code_verifier: str
    state: str


def create_login(
    client_id: str = APP_CLIENT_ID, api_url: str = API_URL, locale: str = "de-DE"
) -> LoginRequest:
    verifier = _b64url(secrets.token_bytes(48))
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    state = secrets.token_urlsafe(16)
    query = urlencode({
        "response_type": "code",
        "response_mode": "form_post",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "scope": OAUTH_SCOPE,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        "ui_locales": locale,
    })
    return LoginRequest(f"{api_url}/connect/authorize?{query}", verifier, state)


def extract_code(pasted: str) -> str | None:
    """Accept a bare code, a cineville://login-callback?code=... URL, or a pasted <input name="code" ...> tag."""
    text = pasted.strip()
    if not text:
        return None
    if text.startswith("cineville:"):
        return (parse_qs(urlparse(text).query).get("code") or [None])[0]
    if "<input" in text or "value=" in text:
        match = re.search(r'name="code"[^>]*value="([^"]+)"', text) or re.search(
            r'value="([^"]+)"[^>]*name="code"', text
        )
        return match.group(1) if match else None
    # Codes are hex with an optional "-1" style suffix
    return text if re.fullmatch(r"[A-Za-z0-9\-_.]+", text) else None


@dataclass(slots=True)
class Tokens:
    access_token: str
    refresh_token: str
    expires_at: float  # unix timestamp

    @property
    def expired(self) -> bool:
        return time.time() >= self.expires_at - REFRESH_MARGIN

    def as_dict(self) -> dict[str, Any]:
        return {"access_token": self.access_token, "refresh_token": self.refresh_token, "expires_at": self.expires_at}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Tokens:
        return cls(data["access_token"], data["refresh_token"], float(data["expires_at"]))


class CinevilleAuth:
    """Holds the tokens and refreshes them when needed."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        tokens: Tokens | None = None,
        *,
        client_id: str = APP_CLIENT_ID,
        api_url: str = API_URL,
        on_tokens_updated: Callable[[Tokens], Awaitable[None] | None] | None = None,
    ) -> None:
        self._session = session
        self._client_id = client_id
        self._api_url = api_url
        self._on_tokens_updated = on_tokens_updated
        self.tokens = tokens

    async def _token_request(self, fields: dict[str, str]) -> dict[str, Any]:
        try:
            async with self._session.post(
                f"{self._api_url}/connect/token",
                data={"client_id": self._client_id, **fields},
                headers={"Accept": "application/json"},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                status = resp.status
                try:
                    payload = await resp.json(content_type=None)
                except ValueError:
                    payload = None
        except (aiohttp.ClientError, TimeoutError) as err:
            raise CinevilleConnectionError(f"Token request failed: {err}") from err
        if status == 200 and isinstance(payload, dict) and "access_token" in payload:
            return payload
        error = payload.get("error") if isinstance(payload, dict) else None
        if error in ("invalid_grant", "invalid_client", "unauthorized_client"):
            raise CinevilleAuthError(f"Login rejected: {error}")
        if status >= 500 or payload is None:
            raise CinevilleConnectionError(f"Token request failed: HTTP {status}")
        raise CinevilleError(f"Token request failed: HTTP {status} {error or ''}".strip())

    async def _store(self, payload: dict[str, Any]) -> Tokens:
        refresh = payload.get("refresh_token") or (self.tokens.refresh_token if self.tokens else None)
        if not refresh:
            raise CinevilleAuthError("No refresh token returned (offline_access missing?)")
        self.tokens = Tokens(payload["access_token"], refresh, time.time() + int(payload.get("expires_in", 3600)))
        if self._on_tokens_updated:
            result = self._on_tokens_updated(self.tokens)
            if result is not None:
                await result
        return self.tokens

    async def exchange_code(self, code: str, code_verifier: str) -> Tokens:
        payload = await self._token_request({
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": code_verifier,
        })
        return await self._store(payload)

    async def refresh(self) -> Tokens:
        if not self.tokens:
            raise CinevilleAuthError("Not logged in")
        payload = await self._token_request({"grant_type": "refresh_token", "refresh_token": self.tokens.refresh_token})
        return await self._store(payload)

    async def access_token(self) -> str:
        if not self.tokens:
            raise CinevilleAuthError("Not logged in")
        if self.tokens.expired:
            await self.refresh()
        return self.tokens.access_token

    async def revoke(self) -> None:
        if not self.tokens:
            return
        try:
            async with self._session.post(
                f"{self._api_url}/connect/revocation",
                data={"client_id": self._client_id, "token": self.tokens.refresh_token, "token_type_hint": "refresh_token"},
                timeout=aiohttp.ClientTimeout(total=30),
            ):
                pass
        except (aiohttp.ClientError, TimeoutError):
            pass  # best effort
        self.tokens = None


# --- Login through Cineville's own pages (email + one-time code) ---------------------------------------

EMAIL_FIELD = "Input.EmailAddress"
OTP_FIELD = "Input.Otp"


@dataclass(slots=True)
class _Form:
    action: str
    fields: dict[str, str] = field(default_factory=dict)  # name -> value (hidden fields keep their value)


class _FormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.forms: list[_Form] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag == "form":
            self.forms.append(_Form(action=a.get("action") or ""))
        elif tag in ("input", "textarea", "select") and self.forms and a.get("name"):
            self.forms[-1].fields[a["name"]] = a.get("value") or ""


def _find_form(html: str, field_name: str) -> _Form | None:
    parser = _FormParser()
    parser.feed(html)
    return next((f for f in parser.forms if field_name in f.fields), None)


_NAME_FIELD = re.compile(r"first.?name|last.?name|given.?name|family.?name|vorname|nachname", re.IGNORECASE)


def _is_signup_page(html: str) -> bool:
    """Cineville's sign-up step for a new account: a form asking for first and last name."""
    parser = _FormParser()
    parser.feed(html)
    return any(_NAME_FIELD.search(name) for form in parser.forms for name in form.fields)


class OtpLogin:
    """One email + one-time-code login, driven step by step by the config flow.

    Uses its own cookie session (Cineville's pages keep an anti-forgery cookie); call close() when done.
    """

    def __init__(self, session: aiohttp.ClientSession, client_id: str = APP_CLIENT_ID, api_url: str = API_URL) -> None:
        self._session = session
        self._request = create_login(client_id, api_url)
        self._page_url: str | None = None
        self._otp_form: _Form | None = None

    @property
    def code_verifier(self) -> str:
        return self._request.code_verifier

    async def _send(self, method: str, url: str, data: dict[str, str] | None = None) -> tuple[str, str]:
        try:
            async with self._session.request(
                method, url, data=data, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status >= 500:
                    raise CinevilleConnectionError(f"Cineville login page: HTTP {resp.status}")
                return str(resp.url), await resp.text()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise CinevilleConnectionError(f"Cineville login page: {err}") from err

    async def start(self, email: str) -> None:
        """Open the login page and submit the email address; Cineville then emails a one-time code."""
        url, html = await self._send("GET", self._request.authorize_url)
        form = _find_form(html, EMAIL_FIELD)
        if form is None:
            raise CinevilleLoginPageError("No email field on Cineville's login page")
        fields = {**form.fields, EMAIL_FIELD: email.strip()}
        url, html = await self._send("POST", urljoin(url, form.action) if form.action else url, fields)
        self._otp_form = _find_form(html, OTP_FIELD)
        if self._otp_form is None:
            # Still on the email page (e.g. unknown address) or an unexpected page
            if _find_form(html, EMAIL_FIELD) is not None:
                raise CinevilleAuthError("Cineville didn't accept the email address")
            raise CinevilleLoginPageError("No code field after submitting the email address")
        self._page_url = url

    async def verify(self, otp: str) -> str:
        """Submit the emailed code; returns the OAuth authorization code (exchange it with code_verifier)."""
        if self._otp_form is None or self._page_url is None:
            raise CinevilleLoginPageError("start() must succeed before verify()")
        form = self._otp_form
        fields = {**form.fields, OTP_FIELD: re.sub(r"\s+", "", otp)}
        url, html = await self._send("POST", urljoin(self._page_url, form.action) if form.action else self._page_url, fields)
        result = _find_form(html, "code")
        if result is not None and result.fields.get("code"):
            if result.fields.get("state") != self._request.state:
                raise CinevilleLoginPageError("State mismatch on the login callback")
            return result.fields["code"]
        retry = _find_form(html, OTP_FIELD)
        if retry is not None:
            # Wrong or expired code: the same page again, with a fresh anti-forgery token
            self._otp_form, self._page_url = retry, url
            raise CinevilleOtpError("Code not accepted")
        if _is_signup_page(html):
            # Unknown email address: Cineville starts creating a new account and asks for a name
            raise CinevilleNoAccountError("No Cineville account for this email address")
        raise CinevilleLoginPageError("Unexpected page after submitting the code")
