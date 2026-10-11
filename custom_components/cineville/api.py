"""Async client for the Cineville (CultureKit) API.

Plain aiohttp, no Home Assistant imports, so it can be tested on its own.
See docs/api/ for the endpoints and their quirks.
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from datetime import date, datetime, timezone
from typing import Any

import aiohttp

from .auth import CinevilleAuth
from .const import API_URL, DEFAULT_LOCALE, MAX_PAGE_LIMIT, MAX_PAGES, TENANT_ID, WEBSITE_URL
from .exceptions import CinevilleAuthError, CinevilleConnectionError, CinevilleError
from .models import City, Showtime, Tenant, Venue

_LOGGER = logging.getLogger(__name__)

TIMEOUT = aiohttp.ClientTimeout(total=30)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


class CinevilleClient:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        auth: CinevilleAuth | None = None,
        api_url: str = API_URL,
        website_url: str = WEBSITE_URL,
        locale: str = DEFAULT_LOCALE,
    ) -> None:
        self._session = session
        self._auth = auth
        self._api_url = api_url.rstrip("/")
        self._website_url = website_url.rstrip("/")
        self._locale = locale

    @property
    def logged_in(self) -> bool:
        return self._auth is not None and self._auth.tokens is not None

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        authenticated: bool = False,
        base_url: str | None = None,
    ) -> Any:
        """Send a request; `path` may also be a _links href (starts with '/')."""
        headers = {"Accept": "application/json", "locale": self._locale}
        if authenticated:
            if not self._auth:
                raise CinevilleAuthError("Not logged in")
            headers["Authorization"] = f"Bearer {await self._auth.access_token()}"
        url = f"{base_url or self._api_url}{path}"
        try:
            async with self._session.request(
                method, url, json=json, params=params, headers=headers, timeout=TIMEOUT
            ) as resp:
                if resp.status == 401:
                    raise CinevilleAuthError("Unauthorized")
                if resp.status >= 400:
                    body = (await resp.text())[:300]
                    if resp.status >= 500:
                        raise CinevilleConnectionError(f"{method} {path}: HTTP {resp.status}")
                    raise CinevilleError(f"{method} {path}: HTTP {resp.status} {body}")
                return await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise CinevilleConnectionError(f"{method} {path}: {err}") from err
        except ValueError as err:  # invalid JSON
            raise CinevilleConnectionError(f"{method} {path}: invalid response") from err

    async def _collect(
        self, method: str, path: str, key: str, *, json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None, authenticated: bool = False,
    ) -> list[dict[str, Any]]:
        """Follow _links.next and return all items of _embedded[key].

        Search endpoints need the same body POSTed to the next href; GET lists just follow it.
        """
        items: list[dict[str, Any]] = []
        for _ in range(MAX_PAGES):
            data = await self._request(method, path, json=json, params=params, authenticated=authenticated)
            items.extend((data.get("_embedded") or {}).get(key) or [])
            next_href = ((data.get("_links") or {}).get("next") or {}).get("href")
            if not next_href:
                return items
            path, params = next_href, None  # the href already carries the query
        _LOGGER.warning("Stopped following %s after %s pages", key, MAX_PAGES)
        return items

    # --- public catalogue ---------------------------------------------------------------

    async def get_tenant(self, tenant_id: str = TENANT_ID) -> Tenant:
        tenants = await self._request("GET", "/api/tenants", base_url=self._website_url)
        for data in tenants:
            if data.get("id") == tenant_id:
                return Tenant.from_api(data)
        raise CinevilleError(f"Tenant {tenant_id} not found")

    async def get_venues(self, city_id: str | None = None) -> list[Venue]:
        params = {"isHidden[eq]": "false", "sort[name]": "asc", "page[limit]": str(MAX_PAGE_LIMIT)}
        if city_id:
            params["collection[cities][in][0]"] = city_id
        venues = await self._collect("GET", "/venues", "venues", params=params)
        return [Venue.from_api(v) for v in venues]

    async def get_cities(self) -> list[City]:
        """City collections that actually have visible venues, named after their venues' city.

        The collection list contains junk/duplicate IDs ('k', 'nu', 'Nürnberg' next to 'nuernberg'),
        so empty collections are dropped and duplicates by name keep the one with the most venues.
        """
        collections = await self._collect(
            "GET", "/collections", "collections",
            params={"collectionGroupId[eq]": "cities", "page[limit]": str(MAX_PAGE_LIMIT)},
        )
        ids = [c["id"] for c in collections]
        venue_lists = await asyncio.gather(*(self.get_venues(cid) for cid in ids))
        best: dict[str, City] = {}
        for cid, venues in zip(ids, venue_lists):
            if not venues:
                continue
            name = Counter(v.city for v in venues if v.city).most_common(1)
            city = City(id=cid, name=name[0][0] if name else cid, venue_count=len(venues))
            key = city.name.casefold()
            if key not in best or city.venue_count > best[key].venue_count:
                best[key] = city
        return sorted(best.values(), key=lambda c: c.name)

    async def get_showtimes(
        self,
        start: datetime,
        end: datetime,
        *,
        city_id: str | None = None,
        venue_ids: list[str] | None = None,
        today: date | None = None,
    ) -> list[Showtime]:
        """All screenings starting in [start, end), sorted by start time.

        Filter by venue IDs if given, otherwise by city. Events without a matched film
        (raw ticketing imports) are skipped, like on cineville.de.
        """
        if not city_id and not venue_ids:
            raise ValueError("city_id or venue_ids is required")
        body: dict[str, Any] = {
            "productionId": {"isNull": False},
            "isHidden": {"eq": False},
            "startDate": {"gte": _iso(start), "lt": _iso(end)},
            "embed": {"production": True, "venue": True},
            "sort": {"startDate": "asc"},
            "page": {"limit": MAX_PAGE_LIMIT},
        }
        if venue_ids:
            body["venueId"] = {"in": list(venue_ids)}
        else:
            body["venue"] = {"collection": {"cities": {"in": [city_id]}}}
        events = await self._collect("POST", "/events/search", "events", json=body)
        showtimes = [s for s in (Showtime.from_api(e, today) for e in events) if s is not None]
        return sorted(showtimes, key=lambda s: (s.start, s.film.title, s.venue.name))

    # --- member data (requires login) ----------------------------------------------------

    async def get_user_id(self) -> str:
        info = await self._request("GET", "/connect/userinfo", authenticated=True)
        return info["sub"]

    async def get_watchlist_ids(self, user_id: str) -> set[str]:
        data = await self._request("GET", f"/users/{user_id}/watchlist/production-ids", authenticated=True)
        return set(data.get("productionIds") or [])

    async def get_seen_ids(self, user_id: str) -> set[str]:
        data = await self._request("GET", f"/users/{user_id}/visit-history/production-ids", authenticated=True)
        return set(data.get("productionIds") or [])
