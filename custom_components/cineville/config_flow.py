"""Config flow for Cineville: pick a city, then the cinemas. Options: cinemas and the Cineville account."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from collections.abc import Mapping

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlowWithReload
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .api import CinevilleClient
from .auth import CinevilleAuth, LoginRequest, Tokens, create_login, extract_code
from .const import (
    CONF_ACCOUNT_NAME,
    CONF_CITY_ID,
    CONF_CITY_NAME,
    CONF_TOKENS,
    CONF_USER_ID,
    CONF_VENUE_IDS,
    DOMAIN,
)
from .exceptions import CinevilleAuthError, CinevilleError
from .models import City, Venue

_LOGGER = logging.getLogger(__name__)


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


CONF_CODE = "code"
CONF_LOG_OUT = "log_out"
ACCOUNT_KEYS = (CONF_TOKENS, CONF_USER_ID, CONF_ACCOUNT_NAME)

LOGIN_SCHEMA = vol.Schema({vol.Required(CONF_CODE): TextSelector()})


async def _complete_login(hass: HomeAssistant, login: LoginRequest, pasted: str) -> tuple[dict[str, Any], str | None]:
    """Exchange the pasted code. Returns (entry data updates, error key)."""
    code = extract_code(pasted)
    if not code:
        return {}, "invalid_code"
    session = async_get_clientsession(hass)
    auth = CinevilleAuth(session)
    try:
        tokens: Tokens = await auth.exchange_code(code, login.code_verifier)
        client = CinevilleClient(session, auth=auth)
        info = await client.get_userinfo()
    except CinevilleAuthError:
        return {}, "login_failed"
    except CinevilleError as err:
        _LOGGER.warning("Cineville login failed: %s", err)
        return {}, "cannot_connect"
    return {
        CONF_TOKENS: tokens.as_dict(),
        CONF_USER_ID: info["sub"],
        CONF_ACCOUNT_NAME: info.get("name") or info.get("email") or "",
    }, None


class CinevilleConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._cities: list[City] = []
        self._city: City | None = None
        self._venues: list[Venue] = []
        self._login: LoginRequest | None = None

    def _client(self) -> CinevilleClient:
        return CinevilleClient(async_get_clientsession(self.hass))

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
                    data={CONF_CITY_ID: self._city.id, CONF_CITY_NAME: self._city.name},
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

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """The Cineville login expired or was revoked."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if self._login is None:
            self._login = create_login()
        if user_input is not None:
            updates, error = await _complete_login(self.hass, self._login, user_input[CONF_CODE])
            if error:
                errors["base"] = error
                if error == "login_failed":
                    self._login = create_login()  # a code only works once, with its own verifier
            else:
                return self.async_update_reload_and_abort(self._get_reauth_entry(), data_updates=updates)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=LOGIN_SCHEMA,
            errors=errors,
            description_placeholders={"url": self._login.authorize_url},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> CinevilleOptionsFlow:
        return CinevilleOptionsFlow()


class CinevilleOptionsFlow(OptionsFlowWithReload):
    """Change the cinemas, or log in to / out of the Cineville account."""

    def __init__(self) -> None:
        self._venues: list[Venue] = []
        self._login: LoginRequest | None = None

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="init", menu_options=["venues", "account"])

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

    async def async_step_account(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if self.config_entry.data.get(CONF_TOKENS):
            return await self.async_step_logout(user_input)
        return await self.async_step_login(user_input)

    async def async_step_login(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if self._login is None:
            self._login = create_login()
        if user_input is not None:
            updates, error = await _complete_login(self.hass, self._login, user_input[CONF_CODE])
            if error:
                errors["base"] = error
                if error == "login_failed":
                    self._login = create_login()
            else:
                self._save_account(updates)
                return self.async_create_entry(data=dict(self.config_entry.options))
        return self.async_show_form(
            step_id="login",
            data_schema=LOGIN_SCHEMA,
            errors=errors,
            description_placeholders={"url": self._login.authorize_url},
        )

    async def async_step_logout(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            if user_input.get(CONF_LOG_OUT):
                tokens = self.config_entry.data.get(CONF_TOKENS)
                if tokens:
                    await CinevilleAuth(async_get_clientsession(self.hass), Tokens.from_dict(tokens)).revoke()
                self._save_account(None)
            return self.async_create_entry(data=dict(self.config_entry.options))
        return self.async_show_form(
            step_id="logout",
            data_schema=vol.Schema({vol.Required(CONF_LOG_OUT, default=False): bool}),
            description_placeholders={"name": self.config_entry.data.get(CONF_ACCOUNT_NAME) or "?"},
        )

    def _save_account(self, updates: dict[str, Any] | None) -> None:
        """Store (or with None: remove) the account and reload, since the options themselves don't change."""
        data = {k: v for k, v in self.config_entry.data.items() if k not in ACCOUNT_KEYS}
        if updates:
            data.update(updates)
        self.hass.config_entries.async_update_entry(self.config_entry, data=data)
        self.hass.config_entries.async_schedule_reload(self.config_entry.entry_id)
