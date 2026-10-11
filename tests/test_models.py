import json
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from custom_components.cineville.models import (
    Film,
    Showtime,
    Tenant,
    Venue,
    cineville_day,
    day_window,
    estimate_end,
    language_label,
    specials_label,
)

BERLIN = ZoneInfo("Europe/Berlin")


@pytest.mark.parametrize(
    ("version", "subs", "expected"),
    [
        ("original", [], "OV"),
        ("original", ["de-DE"], "OmU"),
        ("original", ["en-GB"], "OmeU"),
        ("original", ["de-DE", "en-GB"], "OmeU"),
        ("de-DE", [], "DF"),
        (None, [], None),
        ("en-GB", [], None),
        ("fa", [], None),
    ],
)
def test_language_label(version, subs, expected):
    assert language_label(version, subs) == expected


def test_specials_label():
    assert specials_label(["preview"], []) == "Preview"
    assert specials_label(["sneakPreview", "3d"], ["mit Gästen"]) == "Sneak Preview, 3D, mit Gästen"
    assert specials_label(["classic"], []) == "Klassiker"
    assert specials_label([], ["einführung"]) == "Einführung"
    assert specials_label([], []) is None


def test_estimate_end_rounds_down_to_five_minutes():
    start = datetime(2026, 10, 11, 19, 0, tzinfo=timezone.utc)
    # 19:00 + 107 min + 15 min = 21:02 -> 21:00
    assert estimate_end(start, 107) == datetime(2026, 10, 11, 21, 0, tzinfo=timezone.utc)
    assert estimate_end(start, None) is None


def test_cineville_day_boundary_is_four_am():
    assert cineville_day(datetime(2026, 10, 12, 1, 30, tzinfo=BERLIN), BERLIN) == date(2026, 10, 11)
    assert cineville_day(datetime(2026, 10, 12, 3, 59, tzinfo=BERLIN), BERLIN) == date(2026, 10, 11)
    assert cineville_day(datetime(2026, 10, 12, 4, 0, tzinfo=BERLIN), BERLIN) == date(2026, 10, 12)


def test_day_window_summer_time():
    start, end = day_window(date(2026, 10, 11), BERLIN)
    assert start == datetime(2026, 10, 11, 2, 0, tzinfo=timezone.utc)  # 04:00 CEST
    assert end == datetime(2026, 10, 12, 2, 0, tzinfo=timezone.utc)


def test_day_window_across_dst_change():
    # Clocks go back on 2026-10-25, so that Cineville day lasts 25 hours
    start, end = day_window(date(2026, 10, 24), BERLIN)
    assert start == datetime(2026, 10, 24, 2, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 10, 25, 3, 0, tzinfo=timezone.utc)


def test_showtime_from_sample_event(event):
    s = Showtime.from_api(event, today=date(2026, 10, 11))
    assert s is not None
    assert s.film.title == "Primetime"
    assert s.film.duration == 107
    assert s.film.release_year == 2026
    assert s.film.directors == ("Lance Oppenheim",)
    assert s.film.poster_url.startswith("https://culturekit-assets.imgix.net/")
    assert s.film.trailer_url.endswith(".mp4?fm=mp4")
    assert s.film.is_film
    assert s.venue.name == "Studio Kino"
    assert s.venue.city == "Hamburg"
    assert s.venue.address == "Bernstorffstraße 93-95, 22767 Hamburg"
    assert s.start == datetime(2026, 10, 11, 19, 0, tzinfo=timezone.utc)
    assert s.end == datetime(2026, 10, 11, 20, 51, tzinfo=timezone.utc)
    assert not s.end_is_estimated
    assert s.language_label == "OmU"
    assert s.specials is None
    assert s.ticketing_url.startswith("https://www.kinoheld.de/")


def test_showtime_estimates_missing_end(event):
    event["endDate"] = None
    s = Showtime.from_api(event)
    assert s.end_is_estimated
    assert s.end == datetime(2026, 10, 11, 21, 0, tzinfo=timezone.utc)


def test_showtime_without_production_is_skipped(event):
    del event["_embedded"]["production"]
    assert Showtime.from_api(event) is None


def test_showtime_as_dict_is_json_serialisable(event):
    data = Showtime.from_api(event).as_dict()
    text = json.dumps(data)
    assert '"start": "2026-10-11T19:00:00+00:00"' in text
    assert data["film"]["premiere_date"] == "2026-09-24"


def test_film_programme_slot_is_not_a_film():
    film = Film.from_api({"id": "x", "title": "Sneak Preview", "attributes": {"releaseYear": 0}})
    assert not film.is_film


def test_film_active_highlight_priority():
    data = {
        "id": "x",
        "title": "T",
        "attributes": {
            "highlights": [
                {"type": "freshTrailer"},
                {"type": "tip", "author": "Ana", "startDate": "2026-10-01", "endDate": "2026-10-31"},
                {"type": "filmOfTheWeek", "startDate": "2026-09-01", "endDate": "2026-09-07"},  # expired
            ]
        },
    }
    assert Film.from_api(data, today=date(2026, 10, 11)).highlight == "tip"


def test_venue_strips_stray_whitespace(venue_data):
    venue_data["address"]["street"] = "Schanzenstraße "
    venue_data["address"]["houseNumber"] = "75 im Hof "
    v = Venue.from_api(venue_data)
    assert v.address.startswith("Schanzenstraße 75 im Hof, ")


def test_tenant_from_api_drops_cms_token():
    tenant = Tenant.from_api({
        "id": "cineville.de",
        "country": "DE",
        "cultureKitApiUrl": "https://api.cineville.de",
        "websiteUrl": "https://cineville.de",
        "strapiApiToken": "secret",
        "appAuthClientId": "0d6499ff-c493-4647-8ea3-72cf7543c369",
        "timezone": "Europe/Amsterdam",
        "scheduleWeek": {"startHour": 4, "startWeekday": 3, "lengthInDays": 8},
        "defaultLocale": "de-DE",
        "disabledFeatures": ["notifications"],
    })
    assert tenant.day_start_hour == 4
    assert tenant.app_auth_client_id == "0d6499ff-c493-4647-8ea3-72cf7543c369"
    assert "secret" not in repr(tenant)
