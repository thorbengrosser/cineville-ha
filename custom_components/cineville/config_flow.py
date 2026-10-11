"""Config flow for Cineville: pick a city, then the cinemas."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlowWithReload
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api import CinevilleClient
from .const import CONF_CITY_ID, CONF_CITY_NAME, CONF_VENUE_IDS, DOMAIN
from .exceptions import CinevilleError
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


class CinevilleConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._cities: list[City] = []
        self._city: City | None = None
        self._venues: list[Venue] = []

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

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> CinevilleOptionsFlow:
        return CinevilleOptionsFlow()


class CinevilleOptionsFlow(OptionsFlowWithReload):
    """Change which cinemas are included."""

    def __init__(self) -> None:
        self._venues: list[Venue] = []

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
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
            step_id="init",
            data_schema=_venue_schema(self._venues, selected),
            errors=errors,
            description_placeholders={"city": self.config_entry.data[CONF_CITY_NAME]},
        )
