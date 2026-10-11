from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from custom_components.cineville.const import DOMAIN, SERVICE_GET_PROGRAM
from custom_components.cineville.exceptions import CinevilleConnectionError
from ha_helpers import CLIENT, NOW, mock_entry, showtimes

UPCOMING = "sensor.cineville_hamburg_upcoming_screenings_today"
NEXT = "sensor.cineville_hamburg_next_screening"


@pytest.fixture
def get_showtimes():
    with patch(f"{CLIENT}.get_showtimes", AsyncMock(return_value=showtimes())) as mock:
        yield mock


@pytest.fixture
async def loaded(hass: HomeAssistant, get_showtimes, freezer):
    freezer.move_to(NOW)
    entry = mock_entry(["v-studio"])
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_setup_fetches_todays_window(hass: HomeAssistant, loaded, get_showtimes):
    assert loaded.state is ConfigEntryState.LOADED
    start, end = get_showtimes.await_args.args
    assert start == datetime(2026, 10, 11, 2, 0, tzinfo=timezone.utc)  # 04:00 Berlin
    assert end == datetime(2026, 10, 12, 2, 0, tzinfo=timezone.utc)
    assert get_showtimes.await_args.kwargs["venue_ids"] == ["v-studio"]


async def test_sensors(hass: HomeAssistant, loaded):
    upcoming = hass.states.get(UPCOMING)
    assert upcoming.state == "2"  # the 16:00 UTC screening has already started
    assert upcoming.attributes["films"] == 1
    assert upcoming.attributes["screenings_total"] == 3
    assert upcoming.attributes["day"] == "2026-10-11"

    nxt = hass.states.get(NEXT)
    assert nxt.state == "2026-10-11T19:00:00+00:00"
    assert nxt.attributes["film"] == "Primetime"
    assert nxt.attributes["venue"] == "Studio Kino"
    assert nxt.attributes["language"] == "OmU"


async def test_sensors_follow_the_clock(hass: HomeAssistant, loaded, freezer):
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    freezer.move_to("2026-10-11T19:30:00+00:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(UPCOMING).state == "1"
    assert hass.states.get(NEXT).state == "2026-10-11T20:30:00+00:00"


async def test_get_program_today(hass: HomeAssistant, loaded, get_showtimes):
    calls_before = get_showtimes.await_count
    response = await hass.services.async_call(DOMAIN, SERVICE_GET_PROGRAM, {}, blocking=True, return_response=True)
    assert response["day"] == "2026-10-11"
    assert response["today"] == "2026-10-11"
    assert response["city"] == {"id": "hamburg", "name": "Hamburg"}
    assert [s["id"] for s in response["showtimes"]] == ["e-past", "e-next", "e-late"]
    assert response["showtimes"][1]["film"]["title"] == "Primetime"
    assert get_showtimes.await_count == calls_before  # served from the coordinator


async def test_get_program_other_day_is_fetched_once(hass: HomeAssistant, loaded, get_showtimes):
    calls_before = get_showtimes.await_count
    for _ in range(2):
        response = await hass.services.async_call(
            DOMAIN, SERVICE_GET_PROGRAM, {"date": "2026-10-13"}, blocking=True, return_response=True
        )
    assert response["day"] == "2026-10-13"
    assert get_showtimes.await_count == calls_before + 1  # second call came from the cache
    start, _ = get_showtimes.await_args.args
    assert start == datetime(2026, 10, 13, 2, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("day", ["2026-10-10", "2026-10-19"])
async def test_get_program_date_out_of_range(hass: HomeAssistant, loaded, day):
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, SERVICE_GET_PROGRAM, {"date": day}, blocking=True, return_response=True)


async def test_get_program_unknown_entry(hass: HomeAssistant, loaded):
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, SERVICE_GET_PROGRAM, {"config_entry_id": "nope"}, blocking=True, return_response=True
        )


async def test_setup_retries_when_cineville_is_down(hass: HomeAssistant, get_showtimes, freezer):
    freezer.move_to(NOW)
    get_showtimes.side_effect = CinevilleConnectionError("down")
    entry = mock_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert get_showtimes.await_args.kwargs["venue_ids"] is None  # whole city
    assert get_showtimes.await_args.kwargs["city_id"] == "hamburg"


async def test_unload(hass: HomeAssistant, loaded):
    assert await hass.config_entries.async_unload(loaded.entry_id)
    await hass.async_block_till_done()
    assert loaded.state is ConfigEntryState.NOT_LOADED
