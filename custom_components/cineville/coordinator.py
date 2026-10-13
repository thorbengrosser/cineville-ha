"""Data update coordinator for Cineville."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import CinevilleClient
from .const import (
    ACCOUNT_UPDATE_INTERVAL,
    CONF_ACCOUNT_NAME,
    CONF_CITY_ID,
    CONF_CITY_NAME,
    CONF_USER_ID,
    CONF_VENUE_IDS,
    DAY_CACHE_TTL,
    DEFAULT_DAY_START_HOUR,
    DEFAULT_TIMEZONE,
    DOMAIN,
    UPDATE_INTERVAL,
)
from .exceptions import CinevilleAuthError, CinevilleError
from .models import Showtime, cineville_day, day_window
from .ratings_manager import RatingsManager

_LOGGER = logging.getLogger(__name__)

# Cineville days follow German local time, regardless of Home Assistant's time zone
CINEVILLE_TZ = ZoneInfo(DEFAULT_TIMEZONE)


@dataclass(slots=True)
class Program:
    """All screenings of one Cineville day (04:00–04:00)."""

    day: date
    showtimes: list[Showtime]
    fetched_at: datetime

    def upcoming(self, now: datetime) -> list[Showtime]:
        return [s for s in self.showtimes if s.start >= now]


class CinevilleCoordinator(DataUpdateCoordinator[Program]):
    """Keeps today's program fresh; other days are fetched on demand for the card."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: CinevilleClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.data[CONF_CITY_NAME]}",
            update_interval=UPDATE_INTERVAL,
        )
        self.client = client
        self._day_cache: dict[date, Program] = {}

    @property
    def city_id(self) -> str:
        return self.config_entry.data[CONF_CITY_ID]

    @property
    def venue_ids(self) -> list[str]:
        return list(self.config_entry.options.get(CONF_VENUE_IDS) or [])

    def today(self) -> date:
        return cineville_day(dt_util.utcnow(), CINEVILLE_TZ, DEFAULT_DAY_START_HOUR)

    async def _fetch(self, day: date) -> Program:
        start, end = day_window(day, CINEVILLE_TZ, DEFAULT_DAY_START_HOUR)
        showtimes = await self.client.get_showtimes(
            start, end, city_id=self.city_id, venue_ids=self.venue_ids or None, today=self.today()
        )
        return Program(day=day, showtimes=showtimes, fetched_at=dt_util.utcnow())

    async def _async_update_data(self) -> Program:
        try:
            return await self._fetch(self.today())
        except CinevilleError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN, translation_key="update_failed", translation_placeholders={"error": str(err)}
            ) from err

    async def async_get_program(self, day: date) -> Program:
        """Program for any day: today from the coordinator, other days from a short-lived cache."""
        if self.data is not None and day == self.data.day:
            return self.data
        today = self.today()
        for old in [d for d in self._day_cache if d < today]:
            del self._day_cache[old]
        cached = self._day_cache.get(day)
        if cached and dt_util.utcnow() - cached.fetched_at < DAY_CACHE_TTL:
            return cached
        try:
            program = await self._fetch(day)
        except CinevilleError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="fetch_failed", translation_placeholders={"error": str(err)}
            ) from err
        self._day_cache[day] = program
        return program


@dataclass(slots=True, frozen=True)
class AccountData:
    """The member's watchlist and seen films (production IDs)."""

    watchlist: frozenset[str]
    seen: frozenset[str]


class AccountCoordinator(DataUpdateCoordinator[AccountData]):
    """Watchlist and seen films of one logged-in member.

    Kept separate from the program: if this login expires, HA asks to re-authenticate
    this account, while the program and the other accounts keep working.
    """

    config_entry: ConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: CinevilleClient, user_id: str, name: str
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} account {name}",
            update_interval=ACCOUNT_UPDATE_INTERVAL,
        )
        self.client = client
        self.user_id = user_id
        self.display_name = name

    async def _async_update_data(self) -> AccountData:
        try:
            watchlist = await self.client.get_watchlist_ids(self.user_id)
            seen = await self.client.get_seen_ids(self.user_id)
        except CinevilleAuthError as err:
            # Re-authenticate this particular account (not ConfigEntryAuthFailed, which can't say which one)
            self.config_entry.async_start_reauth(
                self.hass, data={CONF_USER_ID: self.user_id, CONF_ACCOUNT_NAME: self.display_name}
            )
            raise UpdateFailed(
                translation_domain=DOMAIN, translation_key="auth_expired", translation_placeholders={"name": self.display_name}
            ) from err
        except CinevilleError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN, translation_key="update_failed", translation_placeholders={"error": str(err)}
            ) from err
        return AccountData(watchlist=frozenset(watchlist), seen=frozenset(seen))


@dataclass(slots=True)
class CinevilleData:
    """Runtime data of a config entry."""

    program: CinevilleCoordinator
    accounts: dict[str, AccountCoordinator] = field(default_factory=dict)
    ratings: RatingsManager | None = None
    # User IDs of the household; None = every connected account. Friends are connected but not household:
    # their markers show, but "together" logic (seen by everyone, everyone's watchlist) only counts the household.
    household_ids: list[str] | None = None

    def loaded_accounts(self) -> list[AccountCoordinator]:
        """Accounts whose watchlist is currently known (an expired login drops out until renewed)."""
        return [a for a in self.accounts.values() if a.data is not None]

    def in_household(self, user_id: str) -> bool:
        return self.household_ids is None or user_id in self.household_ids

    def household(self) -> list[AccountCoordinator]:
        """Loaded household accounts."""
        return [a for a in self.loaded_accounts() if self.in_household(a.user_id)]

    def flags(self, production_id: str) -> tuple[list[str], list[str]]:
        """(user IDs with the film on their watchlist, user IDs who have seen it)."""
        loaded = self.loaded_accounts()
        return (
            [a.user_id for a in loaded if production_id in a.data.watchlist],
            [a.user_id for a in loaded if production_id in a.data.seen],
        )

    def seen_by_everyone(self, seen_by: list[str]) -> bool:
        """Seen by the whole household (friends don't count)."""
        household = self.household()
        return bool(household) and all(a.user_id in seen_by for a in household)

    def household_wants(self, watchlist_by: list[str]) -> bool:
        """On the watchlist of at least one household member."""
        return any(self.in_household(u) for u in watchlist_by)
