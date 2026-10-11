import base64
import hashlib
import time
from urllib.parse import parse_qs, urlparse

import pytest

from custom_components.cineville.auth import CinevilleAuth, Tokens, create_login, extract_code
from custom_components.cineville.const import APP_CLIENT_ID, REDIRECT_URI
from custom_components.cineville.exceptions import CinevilleAuthError, CinevilleConnectionError


def token_payload(access="access-1", refresh="refresh-1", expires_in=3600):
    return {"access_token": access, "refresh_token": refresh, "expires_in": expires_in,
            "token_type": "Bearer", "scope": "openid api offline_access profile email"}


def test_create_login_builds_pkce_url():
    login = create_login()
    q = {k: v[0] for k, v in parse_qs(urlparse(login.authorize_url).query).items()}
    assert login.authorize_url.startswith("https://api.cineville.de/connect/authorize?")
    assert q["client_id"] == APP_CLIENT_ID
    assert q["redirect_uri"] == REDIRECT_URI
    assert q["response_mode"] == "form_post"
    assert "offline_access" in q["scope"]
    assert q["state"] == login.state
    expected = base64.urlsafe_b64encode(hashlib.sha256(login.code_verifier.encode()).digest()).rstrip(b"=").decode()
    assert q["code_challenge"] == expected
    assert q["code_challenge_method"] == "S256"


def test_each_login_is_unique():
    a, b = create_login(), create_login()
    assert a.code_verifier != b.code_verifier
    assert a.state != b.state


@pytest.mark.parametrize(
    ("pasted", "expected"),
    [
        ("0F4EB72545B0A1658170BAF32480C2B49D60F2C03FF684C61C76744DF542C5DB-1",
         "0F4EB72545B0A1658170BAF32480C2B49D60F2C03FF684C61C76744DF542C5DB-1"),
        ("  ABC123  ", "ABC123"),
        ("cineville://login-callback?code=XYZ&state=s1", "XYZ"),
        ('<input type="hidden" name="code" value="FROMHTML-1" />', "FROMHTML-1"),
        ('<input value="REVERSED" name="code">', "REVERSED"),
        ("", None),
        ("not a code!", None),
    ],
)
def test_extract_code(pasted, expected):
    assert extract_code(pasted) == expected


async def test_exchange_code_stores_tokens_and_notifies(session, fake_api):
    stored = []
    auth = CinevilleAuth(session, api_url=fake_api.url, on_tokens_updated=stored.append)
    fake_api.add("POST", "/connect/token", token_payload())

    tokens = await auth.exchange_code("CODE", "VERIFIER")

    assert tokens.access_token == "access-1"
    assert tokens.refresh_token == "refresh-1"
    assert tokens.expires_at > time.time() + 3000
    assert stored == [tokens]
    assert fake_api.requests[0].form == {"client_id": APP_CLIENT_ID, "grant_type": "authorization_code",
                                         "code": "CODE", "redirect_uri": REDIRECT_URI, "code_verifier": "VERIFIER"}


async def test_async_token_callback_is_awaited(session, fake_api):
    stored = []

    async def save(tokens):
        stored.append(tokens)

    auth = CinevilleAuth(session, api_url=fake_api.url, on_tokens_updated=save)
    fake_api.add("POST", "/connect/token", token_payload())
    await auth.exchange_code("CODE", "VERIFIER")
    assert len(stored) == 1


async def test_access_token_refreshes_when_expired(session, fake_api):
    auth = CinevilleAuth(session, Tokens("old", "refresh-1", time.time() - 10), api_url=fake_api.url)
    # No refresh_token in the response: keep the old one (the server doesn't rotate them today)
    fake_api.add("POST", "/connect/token", {"access_token": "new", "expires_in": 3600})

    assert await auth.access_token() == "new"
    assert auth.tokens.refresh_token == "refresh-1"
    form = fake_api.requests[0].form
    assert form["grant_type"] == "refresh_token"
    assert form["refresh_token"] == "refresh-1"


async def test_valid_token_is_not_refreshed(session, fake_api):
    auth = CinevilleAuth(session, Tokens("still-good", "refresh-1", time.time() + 3600), api_url=fake_api.url)
    assert await auth.access_token() == "still-good"
    assert not fake_api.requests


async def test_invalid_grant_means_reauth(session, fake_api):
    auth = CinevilleAuth(session, Tokens("old", "revoked", time.time() - 10), api_url=fake_api.url)
    fake_api.add("POST", "/connect/token", {"error": "invalid_grant"}, status=400)
    with pytest.raises(CinevilleAuthError):
        await auth.access_token()


async def test_gateway_error_page_is_a_connection_error(session, fake_api):
    auth = CinevilleAuth(session, Tokens("old", "refresh-1", time.time() - 10), api_url=fake_api.url)
    fake_api.add("POST", "/connect/token", status=502, body="<html>Bad gateway</html>")
    with pytest.raises(CinevilleConnectionError):
        await auth.refresh()


async def test_revoke_forgets_tokens(session, fake_api):
    auth = CinevilleAuth(session, Tokens("a", "refresh-1", time.time() + 3600), api_url=fake_api.url)
    fake_api.add("POST", "/connect/revocation", {})
    await auth.revoke()
    assert auth.tokens is None
    assert fake_api.requests[0].form["token"] == "refresh-1"


def test_tokens_roundtrip():
    tokens = Tokens("a", "r", 123.0)
    assert Tokens.from_dict(tokens.as_dict()) == tokens
