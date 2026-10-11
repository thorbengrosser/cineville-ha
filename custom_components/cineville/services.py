"""Services for Cineville. get_program returns a day's program for the dashboard card."""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import (
    ATTR_CONFIG_ENTRY_ID,
    ATTR_DATE,
    CONF_CITY_ID,
    CONF_CITY_NAME,
    DEFAULT_TIMEZONE,
    DOMAIN,
    MAX_DAYS_AHEAD,
    SERVICE_GET_PROGRAM,
)

if TYPE_CHECKING:
    from .coordinator import CinevilleData

GET_PROGRAM_SCHEMA = vol.Schema({
    vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
    vol.Optional(ATTR_DATE): cv.date,
})


def _runtime_data(hass: HomeAssistant, entry_id: str | None) -> CinevilleData:
    entries = [e for e in hass.config_entries.async_entries(DOMAIN) if e.state is ConfigEntryState.LOADED]
    if entry_id:
        entries = [e for e in entries if e.entry_id == entry_id]
        if not entries:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="entry_not_found")
    elif len(entries) > 1:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="entry_required")
    if not entries:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_loaded")
    return entries[0].runtime_data


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    async def get_program(call: ServiceCall) -> ServiceResponse:
        data = _runtime_data(hass, call.data.get(ATTR_CONFIG_ENTRY_ID))
        coordinator = data.program
        today = coordinator.today()
        day: date = call.data.get(ATTR_DATE) or today
        if not today <= day <= today + timedelta(days=MAX_DAYS_AHEAD):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="date_out_of_range",
                translation_placeholders={"first": today.isoformat(), "last": (today + timedelta(days=MAX_DAYS_AHEAD)).isoformat()},
            )
        program = await coordinator.async_get_program(day)
        entry = coordinator.config_entry
        showtimes = []
        for show in program.showtimes:
            item = show.as_dict()
            item["film"]["on_watchlist"], item["film"]["seen"] = data.flags(show.film.id)
            showtimes.append(item)
        return {
            "config_entry_id": entry.entry_id,
            "logged_in": data.account is not None and data.account.data is not None,
            "city": {"id": entry.data[CONF_CITY_ID], "name": entry.data[CONF_CITY_NAME]},
            "day": program.day.isoformat(),
            "today": today.isoformat(),
            "timezone": DEFAULT_TIMEZONE,
            "fetched_at": program.fetched_at.isoformat(),
            "showtimes": showtimes,
        }

    hass.services.async_register(
        DOMAIN, SERVICE_GET_PROGRAM, get_program, schema=GET_PROGRAM_SCHEMA, supports_response=SupportsResponse.ONLY
    )
