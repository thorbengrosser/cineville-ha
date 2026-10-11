"""OAuth login for Cineville member features (watchlist, seen films).

Uses the mobile app's public client: authorization code + PKCE, no client secret.
Home Assistant can't receive the cineville:// redirect, so the authorize URL asks for
response_mode=form_post and the user pastes the code from that (blank) page.
See docs/api/authentication.md.
"""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import aiohttp

from .const import API_URL, APP_CLIENT_ID, OAUTH_SCOPE, REDIRECT_URI
from .exceptions import CinevilleAuthError, CinevilleConnectionError, CinevilleError

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
