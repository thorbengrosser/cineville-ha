"""OtpLogin against a fake copy of Cineville's login pages (structure as recorded on 2026-10-12)."""

from urllib.parse import parse_qs, quote, urlparse

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from custom_components.cineville.auth import OtpLogin
from custom_components.cineville.exceptions import (
    CinevilleAuthError,
    CinevilleLoginPageError,
    CinevilleNoAccountError,
    CinevilleOtpError,
)

GOOD_OTP = "123456"


def email_page(return_url: str, token: str, error: str = "") -> str:
    return f"""<html><body><h1>E-Mail</h1>{error}
      <form method="post" onsubmit="document.getElementById('submitButton').disabled = true; return true;">
        <input type="hidden" name="Input.ReturnUrl" value="{return_url}">
        <input type="email" name="Input.EmailAddress" autocomplete="username">
        <button type="submit" id="submitButton">Weiter</button>
        <input name="__RequestVerificationToken" type="hidden" value="{token}">
      </form></body></html>"""


def otp_page(return_url: str, token: str, error: str = "") -> str:
    return f"""<html><body>{error}
      <form method="post">
        <input type="hidden" name="Input.ReturnUrl" value="{return_url}">
        <input type="hidden" name="EmailAddress" value="me@example.org">
        <input type="hidden" name="TokenLifespanMinutes" value="10">
        <input type="text" name="Input.Otp" autocomplete="one-time-code" inputmode="numeric" maxlength="6">
        <button type="submit">Anmelden</button>
        <input name="__RequestVerificationToken" type="hidden" value="{token}">
      </form></body></html>"""


class FakeLogin:
    """Cineville's login pages, simplified: anti-forgery cookie + token per form, redirects between steps."""

    def __init__(self, layout_changed: bool = False) -> None:
        self.layout_changed = layout_changed
        self.state_override: str | None = None  # simulate a callback for another login attempt
        self.new_account = False  # unknown email: Cineville asks for a name to create an account
        self.posts: list[dict] = []

    def check_antiforgery(self, request: web.Request, form, token: str) -> None:
        assert request.cookies.get(".AspNetCore.Antiforgery") == "cookie-1", "anti-forgery cookie missing"
        assert form["__RequestVerificationToken"] == token, "wrong anti-forgery token"

    async def authorize(self, request: web.Request) -> web.Response:
        callback = "/connect/authorize/callback?" + request.query_string
        resp = web.HTTPFound(f"/auth/login?ReturnUrl={quote(callback, safe='')}")
        resp.set_cookie(".AspNetCore.Antiforgery", "cookie-1")
        raise resp

    async def login_get(self, request: web.Request) -> web.Response:
        if self.layout_changed:
            return web.Response(text="<html><body><form><input name='Username'></form></body></html>", content_type="text/html")
        return web.Response(text=email_page(request.query["ReturnUrl"], "tok-1"), content_type="text/html")

    async def login_post(self, request: web.Request) -> web.Response:
        form = await request.post()
        self.posts.append(dict(form))
        self.check_antiforgery(request, form, "tok-1")
        if form["Input.EmailAddress"] == "unknown@example.org":
            return web.Response(text=email_page(form["Input.ReturnUrl"], "tok-1", "Unbekannt"), content_type="text/html")
        raise web.HTTPFound(f"/auth/verifyotp?returnUrl={quote(form['Input.ReturnUrl'], safe='')}")

    async def otp_get(self, request: web.Request) -> web.Response:
        return web.Response(text=otp_page(request.query["returnUrl"], "tok-2"), content_type="text/html")

    async def otp_post(self, request: web.Request) -> web.Response:
        form = await request.post()
        self.posts.append(dict(form))
        self.check_antiforgery(request, form, form["__RequestVerificationToken"])
        assert form["EmailAddress"] == "me@example.org"  # hidden fields are sent back
        if form["Input.Otp"] != GOOD_OTP:
            return web.Response(text=otp_page(form["Input.ReturnUrl"], "tok-3", "Falscher Code"), content_type="text/html")
        if self.new_account:
            return web.Response(text=f"""<html><body><h1>Wie heißt du?</h1><form method="post">
              <input type="hidden" name="Input.ReturnUrl" value="{form['Input.ReturnUrl']}">
              <input type="text" name="Input.FirstName"><input type="text" name="Input.LastName">
              <button type="submit">Weiter</button></form></body></html>""", content_type="text/html")
        raise web.HTTPFound(form["Input.ReturnUrl"])

    async def callback(self, request: web.Request) -> web.Response:
        state = self.state_override or request.query["state"]
        return web.Response(text=f"""<html><body onload="document.forms[0].submit()">
          <form method="post" action="cineville://login-callback">
            <input type="hidden" name="code" value="OAUTH-CODE-1"><input type="hidden" name="scope" value="openid api">
            <input type="hidden" name="state" value="{state}"><input type="hidden" name="iss" value="https://api.cineville.de">
            <noscript><button>Click to continue</button></noscript></form></body></html>""", content_type="text/html")


@pytest.fixture
async def fake_login(socket_enabled):
    fake = FakeLogin()
    app = web.Application()
    app.router.add_get("/connect/authorize", fake.authorize)
    app.router.add_get("/auth/login", fake.login_get)
    app.router.add_post("/auth/login", fake.login_post)
    app.router.add_get("/auth/verifyotp", fake.otp_get)
    app.router.add_post("/auth/verifyotp", fake.otp_post)
    app.router.add_get("/connect/authorize/callback", fake.callback)
    server = TestServer(app)
    await server.start_server()
    fake.url = str(server.make_url("")).rstrip("/")
    # unsafe=True: aiohttp otherwise ignores cookies from IP-address hosts like 127.0.0.1
    async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as session:
        fake.session = session
        yield fake
    await server.close()


def login(fake) -> OtpLogin:
    return OtpLogin(fake.session, api_url=fake.url)


async def test_full_login(fake_login):
    flow = login(fake_login)
    await flow.start(" me@example.org ")
    assert fake_login.posts[0]["Input.EmailAddress"] == "me@example.org"
    assert fake_login.posts[0]["Input.ReturnUrl"].startswith("/connect/authorize/callback?")
    assert await flow.verify("123 456") == "OAUTH-CODE-1"  # spaces in the typed code are ignored
    assert fake_login.posts[1]["Input.Otp"] == GOOD_OTP
    assert flow.code_verifier


async def test_wrong_code_then_right_code(fake_login):
    flow = login(fake_login)
    await flow.start("me@example.org")
    with pytest.raises(CinevilleOtpError):
        await flow.verify("000000")
    # The retry uses the fresh anti-forgery token from the error page
    assert await flow.verify(GOOD_OTP) == "OAUTH-CODE-1"
    assert fake_login.posts[-1]["__RequestVerificationToken"] == "tok-3"


async def test_unknown_email(fake_login):
    with pytest.raises(CinevilleAuthError) as err:
        await login(fake_login).start("unknown@example.org")
    assert not isinstance(err.value, CinevilleOtpError)


async def test_changed_login_page(fake_login):
    fake_login.layout_changed = True
    with pytest.raises(CinevilleLoginPageError):
        await login(fake_login).start("me@example.org")


async def test_unknown_email_leads_to_signup(fake_login):
    """Cineville creates a new account for unknown addresses and asks for a name after the code."""
    fake_login.new_account = True
    flow = login(fake_login)
    await flow.start("typo@example.org")
    with pytest.raises(CinevilleNoAccountError):
        await flow.verify(GOOD_OTP)


async def test_verify_before_start(fake_login):
    with pytest.raises(CinevilleLoginPageError):
        await login(fake_login).verify(GOOD_OTP)


async def test_state_is_checked(fake_login):
    flow = login(fake_login)
    await flow.start("me@example.org")
    fake_login.state_override = "someone-elses"
    with pytest.raises(CinevilleLoginPageError):
        await flow.verify(GOOD_OTP)


def test_authorize_url_requests_form_post(fake_login):
    flow = login(fake_login)
    q = parse_qs(urlparse(flow._request.authorize_url).query)
    assert q["response_mode"] == ["form_post"]
