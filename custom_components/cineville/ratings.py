"""IMDb and Rotten Tomatoes ratings for Cineville films, via TMDB (matching) and OMDb (ratings).

Cineville has no IMDb IDs and only German titles, so:
  1. TMDB search by (German) title + release year, scored by title, year and director -> TMDB movie
  2. TMDB external_ids -> IMDb ID
  3. OMDb by IMDb ID -> imdbRating, imdbVotes, Rotten Tomatoes
Matching rules come from the spike in docs/design.md (93% of real films matched in Hamburg).
No Home Assistant imports.
"""

from __future__ import annotations

import asyncio
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

import aiohttp

TMDB_URL = "https://api.themoviedb.org/3"
OMDB_URL = "https://www.omdbapi.com/"
TIMEOUT = aiohttp.ClientTimeout(total=20)

# Score needed to accept a TMDB match: title (+3) and year (+2), or either of them plus the director (+3)
MIN_SCORE = 4
# IMDb ratings with fewer votes are too noisy to show (decision in docs/design.md)
MIN_IMDB_VOTES = 100

# Letters that NFKD does not decompose into an ASCII base letter
_TRANSLIT = str.maketrans({"ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "đ": "d", "Đ": "D", "ß": "ss",
                           "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE", "ı": "i"})
_TRAILING_YEAR = re.compile(r"\s*\(\d{4}\)\s*$")


class RatingsError(Exception):
    """TMDB/OMDb unreachable or returned an error; try again later."""


class RatingsAuthError(RatingsError):
    """An API key was rejected. `service` is "tmdb" or "omdb"."""

    def __init__(self, service: str) -> None:
        super().__init__(f"{service.upper()} API key rejected")
        self.service = service


def norm(text: str | None) -> str:
    """Lowercase ASCII, punctuation collapsed, trailing '(2026)' removed: for comparing titles and names."""
    text = _TRAILING_YEAR.sub("", text or "").translate(_TRANSLIT)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


@dataclass(frozen=True, slots=True)
class Rating:
    tmdb_id: int
    imdb_id: str | None
    imdb_rating: float | None = None
    imdb_votes: int | None = None
    rotten_tomatoes: int | None = None  # percent

    @property
    def complete(self) -> bool:
        return self.imdb_rating is not None and self.rotten_tomatoes is not None

    def as_dict(self) -> dict[str, Any]:
        """For the card: the IMDb rating is dropped below MIN_IMDB_VOTES."""
        show_imdb = self.imdb_rating is not None and (self.imdb_votes or 0) >= MIN_IMDB_VOTES
        return {
            "imdb_id": self.imdb_id,
            "imdb": self.imdb_rating if show_imdb else None,
            "imdb_votes": self.imdb_votes,
            "rotten_tomatoes": self.rotten_tomatoes,
            "tmdb_id": self.tmdb_id,
        }


def _parse_number(value: str | None) -> float | None:
    """OMDb numbers: '7.8', '12,345' (votes), '96%' (Rotten Tomatoes), 'N/A'."""
    if not value or value == "N/A":
        return None
    try:
        return float(value.replace(",", "").rstrip("%"))
    except ValueError:
        return None


class RatingsClient:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        tmdb_key: str,
        omdb_key: str,
        *,
        tmdb_url: str = TMDB_URL,
        omdb_url: str = OMDB_URL,
    ) -> None:
        self._session = session
        self._tmdb_key = tmdb_key
        self._omdb_key = omdb_key
        self._tmdb_url = tmdb_url.rstrip("/")
        self._omdb_url = omdb_url

    async def _get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            async with self._session.get(url, params=params, timeout=TIMEOUT) as resp:
                if resp.status == 401:
                    raise RatingsAuthError("omdb" if url.startswith(self._omdb_url) else "tmdb")
                if resp.status >= 400:
                    raise RatingsError(f"{url.split('/')[2]}: HTTP {resp.status}")
                return await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise RatingsError(f"{url.split('/')[2]}: {err}") from err

    async def _tmdb(self, path: str, **params: Any) -> dict[str, Any]:
        return await self._get(f"{self._tmdb_url}{path}", {"api_key": self._tmdb_key, **params})

    async def _omdb(self, **params: Any) -> dict[str, Any]:
        data = await self._get(self._omdb_url, {"apikey": self._omdb_key, **params})
        if data.get("Response") == "False" and "api key" in str(data.get("Error", "")).lower():
            raise RatingsAuthError("omdb")
        return data

    async def validate(self) -> None:
        """Raise RatingsAuthError if either key is wrong (cheap calls; used by the options flow)."""
        await self._tmdb("/configuration")
        await self._omdb(i="tt0068182")  # Aguirre, der Zorn Gottes

    async def _directors(self, movie_id: int) -> set[str]:
        crew = (await self._tmdb(f"/movie/{movie_id}/credits")).get("crew") or []
        return {norm(c.get("name")) for c in crew if c.get("job") == "Director"}

    async def match(self, title: str, year: int | None, directors: tuple[str, ...] | list[str] = ()) -> dict[str, Any] | None:
        """Best TMDB movie for a Cineville film, or None if nothing scores high enough."""
        query = _TRAILING_YEAR.sub("", title)
        candidates: list[dict[str, Any]] = []
        for params in ([{"year": year}] if year else []) + [{}]:
            results = await self._tmdb("/search/movie", query=query, language="de-DE", include_adult="false", **params)
            candidates = (results.get("results") or [])[:8]
            if candidates:
                break
        if not candidates:
            return None

        want_title = norm(title)
        want_dirs = {norm(d) for d in directors if d}
        scored: list[list[Any]] = []
        for movie in candidates:
            score = 0
            if want_title in (norm(movie.get("title")), norm(movie.get("original_title"))):
                score += 3
            released = movie.get("release_date") or ""
            if year and released[:4].isdigit():
                diff = abs(int(released[:4]) - year)
                score += 2 if diff == 0 else (1 if diff == 1 else -2)
            scored.append([score, movie])
        scored.sort(key=lambda e: (-e[0], -(e[1].get("popularity") or 0)))

        if want_dirs:
            # Director overlap confirms a match or breaks a tie between same-title films
            top = scored[:3]
            crews = await asyncio.gather(*(self._directors(e[1]["id"]) for e in top))
            for entry, crew in zip(top, crews):
                if crew & want_dirs:
                    entry[0] += 3
            scored.sort(key=lambda e: (-e[0], -(e[1].get("popularity") or 0)))

        best_score, best = scored[0]
        return best if best_score >= MIN_SCORE else None

    async def ratings_for(self, movie: dict[str, Any]) -> Rating:
        imdb_id = (await self._tmdb(f"/movie/{movie['id']}/external_ids")).get("imdb_id") or None
        if not imdb_id:
            return Rating(tmdb_id=movie["id"], imdb_id=None)
        data = await self._omdb(i=imdb_id)
        rt = next((r.get("Value") for r in data.get("Ratings") or [] if r.get("Source") == "Rotten Tomatoes"), None)
        votes = _parse_number(data.get("imdbVotes"))
        rt_value = _parse_number(rt)
        return Rating(
            tmdb_id=movie["id"],
            imdb_id=imdb_id,
            imdb_rating=_parse_number(data.get("imdbRating")),
            imdb_votes=int(votes) if votes is not None else None,
            rotten_tomatoes=int(rt_value) if rt_value is not None else None,
        )

    async def lookup(self, title: str, year: int | None, directors: tuple[str, ...] | list[str] = ()) -> Rating | None:
        """Ratings for a Cineville film; None when it can't be matched on TMDB."""
        movie = await self.match(title, year, directors)
        if movie is None:
            return None
        return await self.ratings_for(movie)
