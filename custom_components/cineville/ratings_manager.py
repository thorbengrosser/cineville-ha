"""Ratings cache for Cineville films, persisted in HA storage.

Each production ID is looked up once and then refreshed on a schedule:
complete ratings weekly, incomplete ones daily (new releases gain votes quickly), unmatched films every 3 days.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from dataclasses import asdict
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .models import Film
from .ratings import Rating, RatingsAuthError, RatingsClient, RatingsError

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.ratings"

TTL_COMPLETE = timedelta(days=7)
TTL_INCOMPLETE = timedelta(days=1)
TTL_NO_MATCH = timedelta(days=3)
# Stay well below OMDb's free tier (1000 requests/day); one OMDb call per lookup
MAX_LOOKUPS_PER_DAY = 800
PARALLEL_LOOKUPS = 4


class RatingsManager:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: RatingsClient) -> None:
        self.hass = hass
        self._entry = entry
        self._client = client
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._films: dict[str, dict[str, Any]] = {}
        self._inflight: dict[str, asyncio.Task[None]] = {}
        self._semaphore = asyncio.Semaphore(PARALLEL_LOOKUPS)
        self._budget_day: date | None = None
        self._budget_used = 0
        self.disabled_reason: str | None = None

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self._films = data.get("films", {})

    def _save(self) -> None:
        self._store.async_delay_save(lambda: {"films": self._films}, 10)

    def get(self, production_id: str) -> Rating | None:
        """Cached rating (also while it's being refreshed); None if unknown or unmatched."""
        cached = self._films.get(production_id)
        if not cached or cached.get("status") != "found":
            return None
        return Rating(**cached["rating"])

    def _is_fresh(self, production_id: str, now: datetime) -> bool:
        cached = self._films.get(production_id)
        if not cached:
            return False
        checked = dt_util.parse_datetime(cached.get("checked", ""))
        if checked is None:
            return False
        if cached.get("status") == "no_match":
            ttl = TTL_NO_MATCH
        else:
            ttl = TTL_COMPLETE if Rating(**cached["rating"]).complete else TTL_INCOMPLETE
        return now - checked < ttl

    def _take_budget(self) -> bool:
        today = dt_util.utcnow().date()
        if self._budget_day != today:
            self._budget_day, self._budget_used = today, 0
        if self._budget_used >= MAX_LOOKUPS_PER_DAY:
            return False
        self._budget_used += 1
        return True

    async def _lookup(self, film: Film) -> None:
        async with self._semaphore:
            if self.disabled_reason or not self._take_budget():
                return
            try:
                rating = await self._client.lookup(film.title, film.release_year, film.directors)
            except RatingsAuthError as err:
                self.disabled_reason = str(err)
                _LOGGER.warning("Cineville ratings disabled until the keys are fixed: %s", err)
                return
            except RatingsError as err:
                _LOGGER.debug("Rating lookup for %s failed, retrying later: %s", film.title, err)
                return
        entry: dict[str, Any] = {"checked": dt_util.utcnow().isoformat(), "title": film.title}
        if rating is None:
            entry["status"] = "no_match"
        else:
            entry["status"] = "found"
            entry["rating"] = asdict(rating)
        self._films[film.id] = entry
        self._save()

    async def async_ensure(self, films: Iterable[Film], timeout: float | None = None) -> None:
        """Look up films without a fresh cached rating; wait at most `timeout` seconds.

        Lookups that don't finish in time keep running in the background.
        Programme slots without a release year (Sneak Preview etc.) are skipped.
        """
        if self.disabled_reason:
            return
        now = dt_util.utcnow()
        tasks = []
        for film in {f.id: f for f in films}.values():
            if not film.is_film or self._is_fresh(film.id, now):
                continue
            task = self._inflight.get(film.id)
            if task is None:
                task = self._entry.async_create_background_task(
                    self.hass, self._lookup(film), f"{DOMAIN} rating {film.title}"
                )
                self._inflight[film.id] = task
                task.add_done_callback(lambda _t, pid=film.id: self._inflight.pop(pid, None))
            tasks.append(task)
        if tasks and timeout != 0:
            await asyncio.wait(tasks, timeout=timeout)
