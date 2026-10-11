"""Shared helpers for the Home Assistant tests."""

from __future__ import annotations

import time
from datetime import date

from conftest import load_sample, make_event
from custom_components.cineville.const import (
    CONF_ACCOUNT_NAME,
    CONF_CITY_ID,
    CONF_CITY_NAME,
    CONF_TOKENS,
    CONF_USER_ID,
    CONF_VENUE_IDS,
    DOMAIN,
)
from custom_components.cineville.models import City, Showtime, Venue
from pytest_homeassistant_custom_component.common import MockConfigEntry

# Tests run with the clock frozen here: 20:00 in Berlin, Cineville day 2026-10-11
NOW = "2026-10-11T18:00:00+00:00"
TODAY = date(2026, 10, 11)

CLIENT = "custom_components.cineville.api.CinevilleClient"

CITIES = [City("hamburg", "Hamburg", 3), City("koeln", "Köln", 11)]
VENUES = [
    Venue("v-abaton", "Abaton-Kino", "abaton", "Hamburg", "Allendeplatz 3, 20146 Hamburg"),
    Venue("v-studio", "Studio Kino", "studio", "Hamburg", "Bernstorffstraße 93-95, 22767 Hamburg"),
    Venue("v-zeise", "zeise kinos", "zeise", "Hamburg", "Friedensallee 7-9, 22765 Hamburg"),
]


def showtimes() -> list[Showtime]:
    """Primetime at 16:00 (already started), 19:00 and 20:30 UTC."""
    base = load_sample("event-with-embeds")
    events = [
        make_event(base, "e-past", "2026-10-11T16:00:00.000Z"),
        make_event(base, "e-next", "2026-10-11T19:00:00.000Z"),
        make_event(base, "e-late", "2026-10-11T20:30:00.000Z"),
    ]
    return [Showtime.from_api(e, TODAY) for e in events]


# Production ID of "Primetime" in the sample event
PRIMETIME = "f660827c-8cd2-4ea2-878f-b3bc930edd0c"
USER_ID = "user-1"


def account_data() -> dict:
    return {
        CONF_TOKENS: {"access_token": "access-1", "refresh_token": "refresh-1", "expires_at": time.time() + 3600},
        CONF_USER_ID: USER_ID,
        CONF_ACCOUNT_NAME: "Test User",
    }


def mock_entry(venue_ids: list[str] | None = None, *, logged_in: bool = False) -> MockConfigEntry:
    data = {CONF_CITY_ID: "hamburg", CONF_CITY_NAME: "Hamburg"}
    if logged_in:
        data |= account_data()
    return MockConfigEntry(
        domain=DOMAIN,
        title="Cineville Hamburg",
        unique_id="hamburg",
        data=data,
        options={CONF_VENUE_IDS: venue_ids or []},
    )
