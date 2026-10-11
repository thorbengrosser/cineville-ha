"""The Cineville integration."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .api import CinevilleClient
from .auth import CinevilleAuth, Tokens
from .const import CONF_OMDB_KEY, CONF_TMDB_KEY, CONF_TOKENS, CONF_USER_ID, DOMAIN
from .coordinator import AccountCoordinator, CinevilleCoordinator, CinevilleData
from .ratings import RatingsClient
from .ratings_manager import RatingsManager
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

# The dashboard card ships with the integration and is loaded into the frontend automatically
CARD_URL_PATH = "/cineville_static"
CARD_FILE = "cineville-card.js"

type CinevilleConfigEntry = ConfigEntry[CinevilleData]


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
    session = async_get_clientsession(hass)
    auth = None
    if entry.data.get(CONF_TOKENS) and entry.data.get(CONF_USER_ID):

        @callback
        def save_tokens(tokens: Tokens) -> None:
            # Access tokens are renewed hourly; keep the stored copy current
            hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_TOKENS: tokens.as_dict()})

        auth = CinevilleAuth(session, Tokens.from_dict(entry.data[CONF_TOKENS]), on_tokens_updated=save_tokens)

    client = CinevilleClient(session, auth=auth)
    program = CinevilleCoordinator(hass, entry, client)
    await program.async_config_entry_first_refresh()

    account = None
    if auth is not None:
        account = AccountCoordinator(hass, entry, client)
        # Not first_refresh: a failed login must not stop the program from loading.
        # On an auth error the coordinator starts HA's re-authentication flow instead.
        await account.async_refresh()

    ratings = None
    if entry.data.get(CONF_TMDB_KEY) and entry.data.get(CONF_OMDB_KEY):
        ratings = RatingsManager(
            hass, entry, RatingsClient(session, entry.data[CONF_TMDB_KEY], entry.data[CONF_OMDB_KEY])
        )
        await ratings.async_load()

        @callback
        def update_ratings() -> None:
            # Look up today's films in the background after each program update
            if program.data is not None:
                hass.async_create_task(ratings.async_ensure([s.film for s in program.data.showtimes], timeout=0))

        entry.async_on_unload(program.async_add_listener(update_ratings))
        update_ratings()

    entry.runtime_data = CinevilleData(program=program, account=account, ratings=ratings)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: CinevilleConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
