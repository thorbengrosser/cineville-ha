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
from . import accounts as account_store
from .const import CONF_ACCOUNT_NAME, CONF_OMDB_KEY, CONF_TMDB_KEY, CONF_TOKENS, CONF_USER_ID, DOMAIN
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
    program = CinevilleCoordinator(hass, entry, CinevilleClient(session))
    await program.async_config_entry_first_refresh()

    accounts: dict[str, AccountCoordinator] = {}
    for stored in account_store.accounts(dict(entry.data)):
        user_id = stored[CONF_USER_ID]

        @callback
        def save_tokens(tokens: Tokens, user_id: str = user_id) -> None:
            # Access tokens are renewed hourly; keep the stored copy current
            hass.config_entries.async_update_entry(
                entry, data=account_store.with_tokens(dict(entry.data), user_id, tokens.as_dict())
            )

        auth = CinevilleAuth(session, Tokens.from_dict(stored[CONF_TOKENS]), on_tokens_updated=save_tokens)
        coordinator = AccountCoordinator(
            hass, entry, CinevilleClient(session, auth=auth), user_id, stored.get(CONF_ACCOUNT_NAME) or "?"
        )
        # Not first_refresh: a failed login must not stop the program from loading.
        # On an auth error the coordinator starts re-authentication for that account instead.
        await coordinator.async_refresh()
        accounts[user_id] = coordinator

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

    entry.runtime_data = CinevilleData(program=program, accounts=accounts, ratings=ratings)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: CinevilleConfigEntry) -> bool:
    """Version 1 stored one account in entry.data; version 2 keeps a list of accounts."""
    if entry.version > 2:
        return False  # downgrade from a future version
    if entry.version == 1:
        hass.config_entries.async_update_entry(entry, data=account_store.migrate_v1(dict(entry.data)), version=2)
        _LOGGER.debug("Migrated %s to config entry version 2", entry.title)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: CinevilleConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
