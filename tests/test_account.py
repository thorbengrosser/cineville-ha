"""Login, logout, re-authentication and the watchlist features."""

import time
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.cineville.auth import Tokens
from custom_components.cineville.const import CONF_ACCOUNT_NAME, CONF_TOKENS, CONF_USER_ID, DOMAIN, SERVICE_GET_PROGRAM
from custom_components.cineville.exceptions import CinevilleAuthError
from ha_helpers import CLIENT, NOW, PRIMETIME, USER_ID, mock_entry, showtimes

AUTH = "custom_components.cineville.auth.CinevilleAuth"
WATCHLIST_SENSOR = "sensor.cineville_hamburg_watchlist_films_today"


@pytest.fixture
def api(freezer):
    freezer.move_to(NOW)
    with (
        patch(f"{CLIENT}.get_showtimes", AsyncMock(return_value=showtimes())) as get_showtimes,
        patch(f"{CLIENT}.get_watchlist_ids", AsyncMock(return_value={PRIMETIME, "other-film"})) as watchlist,
        patch(f"{CLIENT}.get_seen_ids", AsyncMock(return_value=set())) as seen,
        patch(f"{CLIENT}.get_userinfo", AsyncMock(return_value={"sub": USER_ID, "name": "Test User"})) as userinfo,
        patch(f"{AUTH}.exchange_code", AsyncMock(return_value=Tokens("new-access", "new-refresh", time.time() + 3600))) as exchange,
        patch(f"{AUTH}.revoke", AsyncMock()) as revoke,
    ):
        yield {"showtimes": get_showtimes, "watchlist": watchlist, "seen": seen, "userinfo": userinfo,
               "exchange": exchange, "revoke": revoke}


async def setup(hass: HomeAssistant, entry):
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def open_account_step(hass: HomeAssistant, entry):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    return await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "account"})


async def test_login_via_options(hass: HomeAssistant, api):
    entry = await setup(hass, mock_entry())
    assert hass.states.get(WATCHLIST_SENSOR) is None  # not logged in yet

    result = await open_account_step(hass, entry)
    assert result["step_id"] == "login"
    url = result["description_placeholders"]["url"]
    assert url.startswith("https://api.cineville.de/connect/authorize?") and "response_mode=form_post" in url

    pasted = '<input type="hidden" name="code" value="THE-CODE-1" />'
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"code": pasted})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    code, verifier = api["exchange"].await_args.args
    assert code == "THE-CODE-1"
    assert verifier  # the verifier belonging to the link that was shown
    assert entry.data[CONF_USER_ID] == USER_ID
    assert entry.data[CONF_ACCOUNT_NAME] == "Test User"
    assert entry.data[CONF_TOKENS]["refresh_token"] == "new-refresh"

    # The entry was reloaded with the account: the watchlist sensor exists now
    assert entry.state is ConfigEntryState.LOADED
    state = hass.states.get(WATCHLIST_SENSOR)
    assert state.state == "1"
    assert [f["title"] for f in state.attributes["films"]] == ["Primetime"]
    assert state.attributes["films"][0]["start"] == "2026-10-11T19:00:00+00:00"  # first one that hasn't started
    api["watchlist"].assert_awaited_with(USER_ID)


@pytest.mark.parametrize(
    ("pasted", "exchange_error", "expected"),
    [("not a code!", None, "invalid_code"), ("EXPIRED-CODE", CinevilleAuthError("invalid_grant"), "login_failed")],
)
async def test_login_errors(hass: HomeAssistant, api, pasted, exchange_error, expected):
    entry = await setup(hass, mock_entry())
    api["exchange"].side_effect = exchange_error
    result = await open_account_step(hass, entry)
    first_url = result["description_placeholders"]["url"]
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"code": pasted})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}
    # A rejected code gets a fresh link (codes are single-use and bound to their verifier)
    assert (result["description_placeholders"]["url"] != first_url) == (expected == "login_failed")
    assert CONF_TOKENS not in entry.data


async def test_logout(hass: HomeAssistant, api):
    entry = await setup(hass, mock_entry(logged_in=True))
    result = await open_account_step(hass, entry)
    assert result["step_id"] == "logout"
    assert result["description_placeholders"] == {"name": "Test User"}

    result = await hass.config_entries.options.async_configure(result["flow_id"], {"log_out": True})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    api["revoke"].assert_awaited_once()
    assert CONF_TOKENS not in entry.data
    assert CONF_USER_ID not in entry.data
    assert entry.state is ConfigEntryState.LOADED


async def test_program_marks_watchlist_and_seen(hass: HomeAssistant, api):
    api["seen"].return_value = {PRIMETIME}
    await setup(hass, mock_entry(logged_in=True))
    response = await hass.services.async_call(DOMAIN, SERVICE_GET_PROGRAM, {}, blocking=True, return_response=True)
    assert response["logged_in"] is True
    film = response["showtimes"][0]["film"]
    assert film["on_watchlist"] is True
    assert film["seen"] is True
    # Seen films don't count as "watchlist films today"
    assert hass.states.get(WATCHLIST_SENSOR).state == "0"


async def test_program_without_login_has_no_flags(hass: HomeAssistant, api):
    await setup(hass, mock_entry())
    response = await hass.services.async_call(DOMAIN, SERVICE_GET_PROGRAM, {}, blocking=True, return_response=True)
    assert response["logged_in"] is False
    assert response["showtimes"][0]["film"]["on_watchlist"] is False


async def test_expired_login_starts_reauth_but_program_keeps_working(hass: HomeAssistant, api):
    api["watchlist"].side_effect = CinevilleAuthError("Unauthorized")
    entry = await setup(hass, mock_entry(logged_in=True))

    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get("sensor.cineville_hamburg_upcoming_screenings_today").state == "2"
    assert hass.states.get(WATCHLIST_SENSOR).state == "unavailable"
    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == [config_entries.SOURCE_REAUTH]

    # Completing the re-authentication stores the new login
    api["watchlist"].side_effect = None
    result = await hass.config_entries.flow.async_configure(flows[0]["flow_id"], {"code": "FRESH-CODE"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    await hass.async_block_till_done()
    assert entry.data[CONF_TOKENS]["access_token"] == "new-access"
    assert hass.states.get(WATCHLIST_SENSOR).state == "1"
