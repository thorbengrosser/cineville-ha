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
from .coordinator import CinevilleCoordinator
from .entity import CinevilleEntity
from .models import Showtime

# The data only changes every 30 minutes, but "upcoming" depends on the clock
CLOCK_TICK = timedelta(minutes=1)


async def async_setup_entry(
    hass: HomeAssistant, entry: CinevilleConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities([UpcomingScreeningsSensor(coordinator), NextScreeningSensor(coordinator)])


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
