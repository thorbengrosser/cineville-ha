"""Config flow for Cineville: pick a city, then the cinemas.

Options: cinemas, Cineville accounts (several people; email + one-time code, or a manual fallback) and ratings keys.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlowWithReload
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession, async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from . import accounts as account_store
from .api import CinevilleClient
from .auth import CinevilleAuth, LoginRequest, OtpLogin, Tokens, create_login, extract_code
from .const import (
    CONF_ACCOUNT_NAME,
    CONF_ACCOUNTS,
    CONF_CITY_ID,
    CONF_CITY_NAME,
    CONF_EMAIL,
    CONF_OMDB_KEY,
    CONF_TMDB_KEY,
    CONF_TOKENS,
    CONF_USER_ID,
    CONF_VENUE_IDS,
    DOMAIN,
)
from .exceptions import (
    CinevilleAuthError,
    CinevilleError,
    CinevilleLoginPageError,
    CinevilleNoAccountError,
    CinevilleOtpError,
)
from .models import City, Venue
from .ratings import RatingsAuthError, RatingsClient, RatingsError

_LOGGER = logging.getLogger(__name__)

CONF_CODE = "code"
CONF_REMOVE = "remove"


def _venue_schema(venues: list[Venue], selected: list[str]) -> vol.Schema:
    options = [SelectOptionDict(value=v.id, label=v.name) for v in venues]
    return vol.Schema({
        vol.Required(CONF_VENUE_IDS, default=selected): SelectSelector(
            SelectSelectorConfig(options=options, multiple=True, mode=SelectSelectorMode.LIST)
        )
    })


def _to_stored(selected: list[str], venues: list[Venue]) -> list[str]:
    """All cinemas selected -> store [] ('whole city'), so newly added cinemas show up automatically."""
    return [] if set(selected) >= {v.id for v in venues} else list(selected)


def _email_schema(suggested: str | None = None) -> vol.Schema:
    return vol.Schema({
        vol.Required(CONF_EMAIL, description={"suggested_value": suggested}): TextSelector(
            TextSelectorConfig(type=TextSelectorType.EMAIL, autocomplete="email")
        )
    })


OTP_SCHEMA = vol.Schema({
    vol.Required(CONF_CODE): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT, autocomplete="one-time-code"))
})
PASTE_SCHEMA = vol.Schema({vol.Required(CONF_CODE): TextSelector()})


class _Login:
    """One login attempt inside a flow: email + emailed code (default), or pasting the code (fallback)."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.email: str | None = None
        self._otp: OtpLogin | None = None
        self._session: aiohttp.ClientSession | None = None
        self._manual: LoginRequest | None = None

    async def send_code(self, email: str) -> str | None:
        """Ask Cineville to email a one-time code. Returns an error key or None."""
        await self.close()
        # Own session: Cineville's login pages use an anti-forgery cookie, which must not end up in HA's shared session
        self._session = async_create_clientsession(self.hass)
        self._otp = OtpLogin(self._session)
        self.email = email.strip()
        try:
            await self._otp.start(self.email)
        except CinevilleLoginPageError as err:
            _LOGGER.warning("Cineville's login page looks different than expected: %s", err)
            return "login_page_changed"
        except CinevilleAuthError:
            return "invalid_email"
        except CinevilleError as err:
            _LOGGER.warning("Cineville login failed: %s", err)
            return "cannot_connect"
        return None

    async def verify(self, otp: str) -> tuple[dict[str, Any], str | None]:
        """Submit the emailed code. Returns (account dict for accounts.py, error key)."""
        if self._otp is None:
            return {}, "login_page_changed"
        try:
            code = await self._otp.verify(otp)
        except CinevilleOtpError:
            return {}, "invalid_otp"
        except CinevilleNoAccountError:
            return {}, "no_account"
        except CinevilleLoginPageError as err:
            _LOGGER.warning("Cineville's login page looks different than expected: %s", err)
            return {}, "login_page_changed"
        except CinevilleError as err:
            _LOGGER.warning("Cineville login failed: %s", err)
            return {}, "cannot_connect"
        account, error = await _exchange(self.hass, code, self._otp.code_verifier)
        if not error:
            await self.close()
        return account, error

    @property
    def manual_url(self) -> str:
        if self._manual is None:
            self._manual = create_login()
        return self._manual.authorize_url

    async def paste(self, pasted: str) -> tuple[dict[str, Any], str | None]:
        """Fallback: exchange a code pasted from the browser."""
        code = extract_code(pasted)
        if not code:
            return {}, "invalid_code"
        verifier = self._manual.code_verifier if self._manual else ""
        account, error = await _exchange(self.hass, code, verifier)
        if error == "login_failed":
            self._manual = None  # a code only works once, with its own verifier: show a fresh link
        return account, error

    def new_manual_link(self) -> None:
        self._manual = None

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None
        self._otp = None

    @callback
    def async_close_later(self) -> None:
        """For flows that are abandoned halfway (FlowHandler.async_remove is not async)."""
        if self._session is not None:
            self.hass.async_create_task(self.close())


async def _exchange(hass: HomeAssistant, code: str, verifier: str) -> tuple[dict[str, Any], str | None]:
    """OAuth code -> tokens + who logged in. Returns (account dict for accounts.py, error key)."""
    session = async_get_clientsession(hass)
    auth = CinevilleAuth(session)
    try:
        tokens: Tokens = await auth.exchange_code(code, verifier)
        info = await CinevilleClient(session, auth=auth).get_userinfo()
    except CinevilleAuthError:
        return {}, "login_failed"
    except CinevilleError as err:
        _LOGGER.warning("Cineville login failed: %s", err)
        return {}, "cannot_connect"
    return {
        CONF_USER_ID: info["sub"],
        CONF_ACCOUNT_NAME: account_store.display_name(info),
        CONF_EMAIL: info.get("email") or "",
        CONF_TOKENS: tokens.as_dict(),
    }, None


class CinevilleConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 2

    def __init__(self) -> None:
        self._cities: list[City] = []
        self._city: City | None = None
        self._venues: list[Venue] = []
        self._login: _Login | None = None
        self._reauth_user: dict[str, Any] = {}

    def _client(self) -> CinevilleClient:
        return CinevilleClient(async_get_clientsession(self.hass))

    @callback
    def async_remove(self) -> None:
        if self._login:
            self._login.async_close_later()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        # After a connection error the form is submitted empty: that's a retry, so reload the cities
        city_id = (user_input or {}).get(CONF_CITY_ID)
        city = next((c for c in self._cities if c.id == city_id), None)
        if city is not None:
            self._city = city
            await self.async_set_unique_id(city.id)
            self._abort_if_unique_id_configured()
            return await self.async_step_venues()

        if not self._cities:
            try:
                self._cities = await self._client().get_cities()
            except CinevilleError as err:
                _LOGGER.warning("Could not load Cineville cities: %s", err)
                errors["base"] = "cannot_connect"
        if not self._cities and not errors:
            return self.async_abort(reason="no_cities")

        default = next((c.id for c in self._cities if c.id == "hamburg"), self._cities[0].id if self._cities else None)
        schema = vol.Schema({
            vol.Required(CONF_CITY_ID, default=default): SelectSelector(
                SelectSelectorConfig(
                    options=[SelectOptionDict(value=c.id, label=c.name) for c in self._cities],
                    mode=SelectSelectorMode.DROPDOWN,
                )
            )
        }) if self._cities else vol.Schema({})
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_venues(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        assert self._city is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input[CONF_VENUE_IDS]:
                errors[CONF_VENUE_IDS] = "no_venues_selected"
            else:
                return self.async_create_entry(
                    title=f"Cineville {self._city.name}",
                    data={CONF_CITY_ID: self._city.id, CONF_CITY_NAME: self._city.name, CONF_ACCOUNTS: []},
                    options={CONF_VENUE_IDS: _to_stored(user_input[CONF_VENUE_IDS], self._venues)},
                )

        if not self._venues:
            try:
                self._venues = await self._client().get_venues(self._city.id)
            except CinevilleError as err:
                _LOGGER.warning("Could not load venues for %s: %s", self._city.id, err)
                return self.async_abort(reason="cannot_connect")

        return self.async_show_form(
            step_id="venues",
            data_schema=_venue_schema(self._venues, [v.id for v in self._venues]),
            errors=errors,
            description_placeholders={"city": self._city.name},
        )

    # --- re-authentication of one account --------------------------------------------------

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """One account's Cineville login expired or was revoked (entry_data names the account)."""
        self._reauth_user = dict(entry_data)
        self._login = _Login(self.hass)
        return await self.async_step_reauth_confirm()

    def _reauth_placeholders(self) -> dict[str, str]:
        return {"name": self._reauth_user.get(CONF_ACCOUNT_NAME) or "?"}

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Step 1: email address (prefilled); Cineville emails a code."""
        assert self._login is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            error = await self._login.send_code(user_input[CONF_EMAIL])
            if error == "login_page_changed":
                return await self.async_step_reauth_manual()
            if error:
                errors["base"] = error
            else:
                return await self.async_step_reauth_code()
        return self._reauth_email_form(errors)

    def _reauth_email_form(self, errors: dict[str, str]) -> ConfigFlowResult:
        assert self._login is not None
        stored = account_store.find(dict(self._get_reauth_entry().data), self._reauth_user.get(CONF_USER_ID, ""))
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_email_schema(self._login.email or (stored or {}).get(CONF_EMAIL)),
            errors=errors,
            description_placeholders=self._reauth_placeholders(),
        )

    async def async_step_reauth_code(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Step 2: the code from Cineville's email."""
        assert self._login is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            account, error = await self._login.verify(user_input[CONF_CODE])
            if error == "login_page_changed":
                return await self.async_step_reauth_manual()
            if error == "no_account":
                return self._reauth_email_form({"base": error})
            if not error:
                if (result := self._finish_reauth(account)) is not None:
                    return result
                # Somebody else logged in: start over with the right email address
                return self._reauth_email_form({"base": "wrong_account"})
            errors["base"] = error
        return self.async_show_form(
            step_id="reauth_code",
            data_schema=OTP_SCHEMA,
            errors=errors,
            description_placeholders={**self._reauth_placeholders(), "email": self._login.email or ""},
        )

    async def async_step_reauth_manual(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Fallback when Cineville's login pages changed: log in in a browser and paste the code."""
        assert self._login is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            account, error = await self._login.paste(user_input[CONF_CODE])
            if not error:
                if (result := self._finish_reauth(account)) is not None:
                    return result
                error = "wrong_account"
                self._login.new_manual_link()
            errors["base"] = error
        return self.async_show_form(
            step_id="reauth_manual",
            data_schema=PASTE_SCHEMA,
            errors=errors,
            description_placeholders={**self._reauth_placeholders(), "url": self._login.manual_url},
        )

    def _finish_reauth(self, account: dict[str, Any]) -> ConfigFlowResult | None:
        """Store the renewed login; None if somebody else logged in (the caller shows the error)."""
        expected = self._reauth_user.get(CONF_USER_ID)
        if expected and account[CONF_USER_ID] != expected:
            return None
        entry = self._get_reauth_entry()
        return self.async_update_reload_and_abort(entry, data=account_store.upsert(dict(entry.data), account))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> CinevilleOptionsFlow:
        return CinevilleOptionsFlow()


class CinevilleOptionsFlow(OptionsFlowWithReload):
    """Change the cinemas, manage Cineville accounts, set the ratings keys."""

    def __init__(self) -> None:
        self._venues: list[Venue] = []
        self._login: _Login | None = None

    @callback
    def async_remove(self) -> None:
        if self._login:
            self._login.async_close_later()

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="init", menu_options=["venues", "account", "ratings"])

    async def async_step_venues(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if not self._venues:
            try:
                self._venues = await CinevilleClient(async_get_clientsession(self.hass)).get_venues(
                    self.config_entry.data[CONF_CITY_ID]
                )
            except CinevilleError:
                return self.async_abort(reason="cannot_connect")

        if user_input is not None:
            if not user_input[CONF_VENUE_IDS]:
                errors[CONF_VENUE_IDS] = "no_venues_selected"
            else:
                return self.async_create_entry(
                    data={**self.config_entry.options, CONF_VENUE_IDS: _to_stored(user_input[CONF_VENUE_IDS], self._venues)}
                )

        stored = self.config_entry.options.get(CONF_VENUE_IDS) or []
        known = {v.id for v in self._venues}
        selected = [v for v in stored if v in known] or [v.id for v in self._venues]
        return self.async_show_form(
            step_id="venues",
            data_schema=_venue_schema(self._venues, selected),
            errors=errors,
            description_placeholders={"city": self.config_entry.data[CONF_CITY_NAME]},
        )

    # --- accounts ----------------------------------------------------------------------------

    async def async_step_account(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Several people can be logged in; their watchlists are combined on the card."""
        connected = account_store.accounts(dict(self.config_entry.data))
        names = ", ".join(a.get(CONF_ACCOUNT_NAME) or "?" for a in connected)
        return self.async_show_menu(
            step_id="account",
            menu_options=["login", "login_manual", *(["logout"] if connected else [])],
            description_placeholders={"names": names or "–"},
        )

    def _get_login(self) -> _Login:
        if self._login is None:
            self._login = _Login(self.hass)
        return self._login

    async def async_step_login(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Add an account, step 1: email address; Cineville emails a one-time code."""
        login = self._get_login()
        errors: dict[str, str] = {}
        if user_input is not None:
            error = await login.send_code(user_input[CONF_EMAIL])
            if error:
                errors["base"] = error
            else:
                return await self.async_step_login_code()
        return self.async_show_form(step_id="login", data_schema=_email_schema(login.email), errors=errors)

    async def async_step_login_code(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Add an account, step 2: the code from Cineville's email."""
        login = self._get_login()
        errors: dict[str, str] = {}
        if user_input is not None:
            account, error = await login.verify(user_input[CONF_CODE])
            if not error:
                return self._add_account(account)
            if error == "no_account":
                # Needs a different email address: back to the first step
                return self.async_show_form(
                    step_id="login", data_schema=_email_schema(login.email), errors={"base": error}
                )
            errors["base"] = error
        return self.async_show_form(
            step_id="login_code",
            data_schema=OTP_SCHEMA,
            errors=errors,
            description_placeholders={"email": login.email or ""},
        )

    async def async_step_login_manual(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Fallback: log in in a browser and paste the code from the blank page."""
        login = self._get_login()
        errors: dict[str, str] = {}
        if user_input is not None:
            account, error = await login.paste(user_input[CONF_CODE])
            if not error:
                return self._add_account(account)
            errors["base"] = error
        return self.async_show_form(
            step_id="login_manual",
            data_schema=PASTE_SCHEMA,
            errors=errors,
            description_placeholders={"url": login.manual_url},
        )

    def _add_account(self, account: dict[str, Any]) -> ConfigFlowResult:
        # Logging in again with a connected account just renews its login
        self._save_data(account_store.upsert(dict(self.config_entry.data), account))
        return self.async_create_entry(data=dict(self.config_entry.options))

    async def async_step_logout(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        connected = account_store.accounts(dict(self.config_entry.data))
        if user_input is not None:
            remove = user_input.get(CONF_REMOVE) or []
            session = async_get_clientsession(self.hass)
            for account in connected:
                if account[CONF_USER_ID] in remove:
                    await CinevilleAuth(session, Tokens.from_dict(account[CONF_TOKENS])).revoke()
            if remove:
                self._save_data(account_store.remove(dict(self.config_entry.data), remove))
            return self.async_create_entry(data=dict(self.config_entry.options))
        options = [SelectOptionDict(value=a[CONF_USER_ID], label=a.get(CONF_ACCOUNT_NAME) or "?") for a in connected]
        return self.async_show_form(
            step_id="logout",
            data_schema=vol.Schema({
                vol.Optional(CONF_REMOVE, default=[]): SelectSelector(
                    SelectSelectorConfig(options=options, multiple=True, mode=SelectSelectorMode.LIST)
                )
            }),
        )

    async def async_step_ratings(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """TMDB + OMDb keys for the IMDb / Rotten Tomatoes badges. Both empty = ratings off."""
        errors: dict[str, str] = {}
        data = self.config_entry.data
        if user_input is not None:
            tmdb = (user_input.get(CONF_TMDB_KEY) or "").strip()
            omdb = (user_input.get(CONF_OMDB_KEY) or "").strip()
            if bool(tmdb) != bool(omdb):
                errors["base"] = "both_keys_needed"
            elif tmdb:
                try:
                    await RatingsClient(async_get_clientsession(self.hass), tmdb, omdb).validate()
                except RatingsAuthError as err:
                    errors["base"] = f"invalid_{err.service}_key"
                except RatingsError:
                    errors["base"] = "cannot_connect"
            if not errors:
                new = {k: v for k, v in data.items() if k not in (CONF_TMDB_KEY, CONF_OMDB_KEY)}
                if tmdb:
                    new |= {CONF_TMDB_KEY: tmdb, CONF_OMDB_KEY: omdb}
                self._save_data(new)
                return self.async_create_entry(data=dict(self.config_entry.options))

        password = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
        schema = vol.Schema({
            vol.Optional(CONF_TMDB_KEY, description={"suggested_value": data.get(CONF_TMDB_KEY)}): password,
            vol.Optional(CONF_OMDB_KEY, description={"suggested_value": data.get(CONF_OMDB_KEY)}): password,
        })
        return self.async_show_form(
            step_id="ratings",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "tmdb_url": "https://www.themoviedb.org/settings/api",
                "omdb_url": "https://www.omdbapi.com/apikey.aspx",
            },
        )

    def _save_data(self, data: dict[str, Any]) -> None:
        """Store changed entry data and reload (the options themselves don't change, so no automatic reload)."""
        self.hass.config_entries.async_update_entry(self.config_entry, data=data)
        self.hass.config_entries.async_schedule_reload(self.config_entry.entry_id)
