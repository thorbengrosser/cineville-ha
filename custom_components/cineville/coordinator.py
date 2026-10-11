"""Data update coordinator for Cineville."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import CinevilleClient
from .const import (
    CONF_CITY_ID,
    CONF_CITY_NAME,
    CONF_VENUE_IDS,
    DAY_CACHE_TTL,
    DEFAULT_DAY_START_HOUR,
    DEFAULT_TIMEZONE,
    DOMAIN,
    UPDATE_INTERVAL,
)
from .exceptions import CinevilleError
from .models import Showtime, cineville_day, day_window

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
