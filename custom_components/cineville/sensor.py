"""Sensors for Cineville: upcoming screenings today and the next screening."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from . import CinevilleConfigEntry
from .coordinator import AccountCoordinator, CinevilleCoordinator, CinevilleData
from .entity import CinevilleEntity
from .models import Showtime

# The data only changes every 30 minutes, but "upcoming" depends on the clock
CLOCK_TICK = timedelta(minutes=1)


async def async_setup_entry(
    hass: HomeAssistant, entry: CinevilleConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    data = entry.runtime_data
    entities: list[SensorEntity] = [UpcomingScreeningsSensor(data.program), NextScreeningSensor(data.program)]
    if data.account is not None:
        entities.append(WatchlistTodaySensor(data))
    async_add_entities(entities)


class _ClockedSensor(CinevilleEntity, SensorEntity):
    """Re-evaluates its state every minute, not only on coordinator updates."""

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(async_track_time_interval(self.hass, self._tick, CLOCK_TICK))

    @callback
    def _tick(self, _now: datetime) -> None:
        self.async_write_ha_state()

    def _upcoming(self) -> list[Showtime]:
        if self.coordinator.data is None:
            return []
        return self.coordinator.data.upcoming(dt_util.utcnow())


class UpcomingScreeningsSensor(_ClockedSensor):
    """Number of screenings still to start today (Cineville day, until 04:00)."""

    _attr_native_unit_of_measurement = "screenings"

    def __init__(self, coordinator: CinevilleCoordinator) -> None:
        super().__init__(coordinator, "upcoming_screenings")

    @property
    def native_value(self) -> int:
        return len(self._upcoming())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        upcoming = self._upcoming()
        data = self.coordinator.data
        return {
            "day": data.day.isoformat() if data else None,
            "films": len({s.film.id for s in upcoming}),
            "screenings_total": len(data.showtimes) if data else 0,
        }


class NextScreeningSensor(_ClockedSensor):
    """Start time of the next screening, with the film as attributes."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: CinevilleCoordinator) -> None:
        super().__init__(coordinator, "next_screening")

    def _next(self) -> Showtime | None:
        upcoming = self._upcoming()
        return upcoming[0] if upcoming else None

    @property
    def native_value(self) -> datetime | None:
        nxt = self._next()
        return nxt.start if nxt else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        nxt = self._next()
        if nxt is None:
            return {}
        return {
            "film": nxt.film.title,
            "venue": nxt.venue.name,
            "language": nxt.language_label,
            "specials": nxt.specials,
            "end": nxt.end.isoformat() if nxt.end else None,
            "poster": nxt.film.poster_url,
            "ticketing_url": nxt.ticketing_url,
        }


class WatchlistTodaySensor(_ClockedSensor):
    """Watchlist films (not seen yet) that still have a screening today. Only when logged in."""

    _attr_native_unit_of_measurement = "films"
    # Keep the film list out of the recorder; it's for the UI and automations only
    _unrecorded_attributes = frozenset({"films"})

    def __init__(self, data: CinevilleData) -> None:
        super().__init__(data.program, "watchlist_today")
        self._data = data
        self._account: AccountCoordinator = data.account  # type: ignore[assignment]

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._account.async_add_listener(self.async_write_ha_state))

    @property
    def available(self) -> bool:
        return super().available and self._account.data is not None

    def _films(self) -> list[Showtime]:
        """First upcoming screening of each watchlist film, in start order."""
        first: dict[str, Showtime] = {}
        for show in self._upcoming():
            on_watchlist, seen = self._data.flags(show.film.id)
            if on_watchlist and not seen and show.film.id not in first:
                first[show.film.id] = show
        return list(first.values())

    @property
    def native_value(self) -> int:
        return len(self._films())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "films": [
                {"title": s.film.title, "start": s.start.isoformat(), "venue": s.venue.name, "language": s.language_label}
                for s in self._films()
            ]
        }
