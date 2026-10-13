"""The Cineville integration."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

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
from .const import CONF_ACCOUNT_NAME, CONF_HOUSEHOLD, CONF_OMDB_KEY, CONF_TMDB_KEY, CONF_TOKENS, CONF_USER_ID, DOMAIN
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
    """Serve frontend/cineville-card.js and make every dashboard load it (no manual resource needed).

    The card is registered as a dashboard resource: dashboards wait for resources before drawing cards.
    (add_extra_js_url loads in parallel with the dashboard, so on a fresh page load the card's code could
    arrive too late and the card showed "Configuration error" until a reload.)
    """
    if hass.http is None or "frontend" not in hass.config.components:
        _LOGGER.debug("Frontend not loaded; not registering the Cineville card")
        return
    from homeassistant.components.http import StaticPathConfig  # noqa: PLC0415

    integration = await async_get_integration(hass, DOMAIN)
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL_PATH, str(Path(__file__).parent / "frontend"), cache_headers=False)]
    )
    # Version in the URL so browsers pick up a new card after an update
    url = f"{CARD_URL_PATH}/{CARD_FILE}?v={integration.version}"
    if not await _async_ensure_resource(hass, url):
        # Resources managed in YAML (or no lovelace): fall back to loading it alongside the frontend
        from homeassistant.components.frontend import add_extra_js_url  # noqa: PLC0415

        add_extra_js_url(hass, url)


def _resource_collection(hass: HomeAssistant) -> Any | None:
    """The storage-mode dashboard resource collection, or None (YAML mode / lovelace not loaded)."""
    data = hass.data.get("lovelace")
    if data is None:
        return None
    mode = getattr(data, "resource_mode", None) or getattr(data, "mode", None)
    resources = getattr(data, "resources", None)
    if mode != "storage" or resources is None or not hasattr(resources, "async_create_item"):
        return None
    return resources


def _is_card_resource(item: dict[str, Any]) -> bool:
    return str(item.get("url", "")).split("?")[0] == f"{CARD_URL_PATH}/{CARD_FILE}"


async def _async_ensure_resource(hass: HomeAssistant, url: str) -> bool:
    """Create or update the card's dashboard resource. False if resources can't be managed here."""
    resources = _resource_collection(hass)
    if resources is None:
        return False
    await resources.async_get_info()  # loads the collection from storage if needed
    existing = [item for item in resources.async_items() if _is_card_resource(item)]
    if not existing:
        await resources.async_create_item({"res_type": "module", "url": url})
        _LOGGER.debug("Registered dashboard resource %s", url)
        return True
    first, *duplicates = existing
    if first.get("url") != url or first.get("type") != "module":
        await resources.async_update_item(first["id"], {"res_type": "module", "url": url})
    for item in duplicates:
        await resources.async_delete_item(item["id"])
    return True


async def async_remove_entry(hass: HomeAssistant, entry: CinevilleConfigEntry) -> None:
    """Remove the card's dashboard resource when the last Cineville entry is deleted."""
    if any(e.entry_id != entry.entry_id for e in hass.config_entries.async_entries(DOMAIN)):
        return
    if (resources := _resource_collection(hass)) is None:
        return
    await resources.async_get_info()
    for item in [i for i in resources.async_items() if _is_card_resource(i)]:
        await resources.async_delete_item(item["id"])


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

    household = entry.options.get(CONF_HOUSEHOLD)
    entry.runtime_data = CinevilleData(
        program=program, accounts=accounts, ratings=ratings, household_ids=list(household) if household is not None else None
    )
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
