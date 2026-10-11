"""Data models for the Cineville API, plus the display rules cineville.de applies.

See docs/api/data-model.md and docs/api/display-logic.md.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .const import (
    DEFAULT_DAY_START_HOUR,
    END_TIME_PADDING_MINUTES,
    HIGHLIGHT_PRIORITY,
    SPECIAL_LABELS_DE,
)


def parse_datetime(value: str | None) -> datetime | None:
    """Parse an API timestamp ('...Z' or '+00:00') into an aware UTC datetime."""
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _clean(value: Any) -> str:
    """Strip the stray whitespace the API has in some address fields."""
    return value.strip() if isinstance(value, str) else ""


def language_label(language_version: str | None, subtitles: list[str] | tuple[str, ...]) -> str | None:
    """OV / OmU / OmeU / DF, following cineville.de's rules for country DE."""
    if language_version == "original":
        if not subtitles:
            return "OV"
        if any("en" in sub for sub in subtitles):
            return "OmeU"
        return "OmU"
    if language_version and "de" in language_version:
        return "DF"
    return None


def specials_label(tags: list[str] | tuple[str, ...], custom_tags: list[str] | tuple[str, ...]) -> str | None:
    """Translated tags plus the cinema's custom tags, joined and capitalised like on cineville.de."""
    parts = [SPECIAL_LABELS_DE.get(tag, tag) for tag in tags] + [t for t in custom_tags if t]
    if not parts:
        return None
    text = ", ".join(parts)
    return text[0].upper() + text[1:]


def estimate_end(start: datetime, duration_minutes: int | None) -> datetime | None:
    """cineville.de's fallback when endDate is missing: start + duration + 15 min, floored to 5 min."""
    if not duration_minutes:
        return None
    end = start + timedelta(minutes=duration_minutes + END_TIME_PADDING_MINUTES)
    return end - timedelta(minutes=end.minute % 5, seconds=end.second, microseconds=end.microsecond)


def cineville_day(now: datetime, tz: ZoneInfo, start_hour: int = DEFAULT_DAY_START_HOUR) -> date:
    """The Cineville day 'now' belongs to: before 04:00 local time it still counts as the previous day."""
    local = now.astimezone(tz)
    return (local - timedelta(hours=start_hour)).date()


def day_window(day: date, tz: ZoneInfo, start_hour: int = DEFAULT_DAY_START_HOUR) -> tuple[datetime, datetime]:
    """UTC [start, end) for a Cineville day: day 04:00 → next day 04:00 local time."""
    start = datetime.combine(day, time(hour=start_hour), tzinfo=tz)
    end = datetime.combine(day + timedelta(days=1), time(hour=start_hour), tzinfo=tz)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def _active_highlight(highlights: list[dict[str, Any]], today: date) -> str | None:
    active = set()
    for item in highlights or []:
        start, end = parse_date(item.get("startDate")), parse_date(item.get("endDate"))
        if (start is None or start <= today) and (end is None or today <= end):
            active.add(item.get("type"))
    return next((kind for kind in HIGHLIGHT_PRIORITY if kind in active), None)


@dataclass(frozen=True, slots=True)
class City:
    """A city collection (collectionGroupId 'cities')."""

    id: str
    name: str
    venue_count: int


@dataclass(frozen=True, slots=True)
class Venue:
    id: str
    name: str
    slug: str
    city: str
    address: str
    latitude: float | None = None
    longitude: float | None = None
    website: str | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Venue:
        addr = data.get("address") or {}
        street = " ".join(p for p in (_clean(addr.get("street")), _clean(addr.get("houseNumber"))) if p)
        town = " ".join(p for p in (_clean(addr.get("postalCode")), _clean(addr.get("city"))) if p)
        return cls(
            id=data["id"],
            name=_clean(data.get("name")),
            slug=data.get("slug", ""),
            city=_clean(addr.get("city")),
            address=", ".join(p for p in (street, town) if p),
            latitude=addr.get("latitude"),
            longitude=addr.get("longitude"),
            website=(data.get("attributes") or {}).get("website") or None,
        )


@dataclass(frozen=True, slots=True)
class Film:
    id: str
    slug: str
    title: str
    poster_url: str | None = None
    cover_url: str | None = None
    trailer_url: str | None = None
    duration: int | None = None
    release_year: int | None = None
    premiere_date: date | None = None
    directors: tuple[str, ...] = ()
    cast: tuple[str, ...] = ()
    spoken_languages: tuple[str, ...] = ()
    min_age: int | None = None
    short_description: str | None = None
    description: str | None = None
    highlight: str | None = None

    @property
    def is_film(self) -> bool:
        """False for programme slots like 'Sneak Preview' (no release year)."""
        return bool(self.release_year)

    @classmethod
    def from_api(cls, data: dict[str, Any], today: date | None = None) -> Film:
        attrs = data.get("attributes") or {}
        texts = data.get("localizableAttributes") or {}
        assets = data.get("assets") or {}

        def asset_url(key: str) -> str | None:
            return (assets.get(key) or {}).get("url") or None

        trailer = asset_url("trailer")
        if trailer and trailer.endswith(".mp4") and "imgix.net" in trailer:
            trailer += "?fm=mp4"  # imgix needs this to serve the video as a plain mp4
        return cls(
            id=data["id"],
            slug=data.get("slug", ""),
            title=_clean(data.get("title")),
            poster_url=asset_url("poster"),
            cover_url=asset_url("cover"),
            trailer_url=trailer,
            duration=attrs.get("duration") or None,
            release_year=attrs.get("releaseYear") or None,
            premiere_date=parse_date(attrs.get("premiereDate")),
            directors=tuple(attrs.get("directors") or ()),
            cast=tuple(attrs.get("cast") or ()),
            spoken_languages=tuple(attrs.get("spokenLanguages") or ()),
            min_age=attrs.get("contentRatingMinimumAge"),
            short_description=texts.get("shortDescription") or None,
            description=texts.get("description") or None,
            highlight=_active_highlight(attrs.get("highlights") or [], today or date.today()),
        )


@dataclass(frozen=True, slots=True)
class Showtime:
    """One screening, flattened the way cineville.de presents it."""

    id: str
    film: Film
    venue: Venue
    start: datetime
    end: datetime | None
    end_is_estimated: bool
    language_version: str | None
    subtitles: tuple[str, ...]
    language_label: str | None
    tags: tuple[str, ...]
    specials: str | None
    ticketing_url: str | None

    @classmethod
    def from_api(cls, event: dict[str, Any], today: date | None = None) -> Showtime | None:
        """Parse an event with embedded production and venue. Returns None for unmatched imports."""
        embedded = event.get("_embedded") or {}
        production, venue = embedded.get("production"), embedded.get("venue")
        start = parse_datetime(event.get("startDate"))
        if not production or not venue or start is None:
            return None
        film = Film.from_api(production, today)
        attrs = event.get("attributes") or {}
        subtitles = tuple(attrs.get("subtitles") or ())
        tags = tuple(attrs.get("tags") or ())
        end = parse_datetime(event.get("endDate"))
        estimated = end is None
        if estimated:
            end = estimate_end(start, film.duration)
        return cls(
            id=event["id"],
            film=film,
            venue=Venue.from_api(venue),
            start=start,
            end=end,
            end_is_estimated=estimated and end is not None,
            language_version=attrs.get("languageVersion"),
            subtitles=subtitles,
            language_label=language_label(attrs.get("languageVersion"), subtitles),
            tags=tags,
            specials=specials_label(tags, (event.get("localizableAttributes") or {}).get("customTags") or ()),
            ticketing_url=event.get("ticketingUrl") or None,
        )

    def as_dict(self) -> dict[str, Any]:
        """JSON-serialisable representation (for the service response / the card)."""
        data = asdict(self)
        data["start"] = self.start.isoformat()
        data["end"] = self.end.isoformat() if self.end else None
        data["film"]["premiere_date"] = self.film.premiere_date.isoformat() if self.film.premiere_date else None
        return data


@dataclass(frozen=True, slots=True)
class Tenant:
    """Per-country configuration from https://cineville.de/api/tenants (CMS token deliberately not kept)."""

    id: str
    country: str
    api_url: str
    website_url: str
    app_auth_client_id: str
    timezone: str
    day_start_hour: int
    default_locale: str
    disabled_features: tuple[str, ...] = field(default=())

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Tenant:
        return cls(
            id=data["id"],
            country=data.get("country", ""),
            api_url=data["cultureKitApiUrl"].rstrip("/"),
            website_url=data.get("websiteUrl", "").rstrip("/"),
            app_auth_client_id=data.get("appAuthClientId", ""),
            timezone=data.get("timezone", "Europe/Berlin"),
            day_start_hour=(data.get("scheduleWeek") or {}).get("startHour", DEFAULT_DAY_START_HOUR),
            default_locale=data.get("defaultLocale", "de-DE"),
            disabled_features=tuple(data.get("disabledFeatures") or ()),
        )
