"""The Cineville integration."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .api import CinevilleClient
from .const import DOMAIN
from .coordinator import CinevilleCoordinator
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

# The dashboard card ships with the integration and is loaded into the frontend automatically
CARD_URL_PATH = "/cineville_static"
CARD_FILE = "cineville-card.js"

type CinevilleConfigEntry = ConfigEntry[CinevilleCoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async_setup_services(hass)
    await _async_register_card(hass)
    return True


async def _async_register_card(hass: HomeAssistant) -> None:
    """Serve frontend/cineville-card.js and add it to every dashboard (no manual resource needed)."""
    if hass.http is None or "frontend" not in hass.config.components:
        _LOGGER.debug("Frontend not loaded; not registering the Cineville card")
        return
    from homeassistant.components.frontend import add_extra_js_url  # noqa: PLC0415
    from homeassistant.components.http import StaticPathConfig  # noqa: PLC0415

    integration = await async_get_integration(hass, DOMAIN)
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL_PATH, str(Path(__file__).parent / "frontend"), cache_headers=False)]
    )
    # Version in the URL so browsers pick up a new card after an update
    add_extra_js_url(hass, f"{CARD_URL_PATH}/{CARD_FILE}?v={integration.version}")


async def async_setup_entry(hass: HomeAssistant, entry: CinevilleConfigEntry) -> bool:
    client = CinevilleClient(async_get_clientsession(hass))
    coordinator = CinevilleCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: CinevilleConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
