"""Accounts: login, several people, logout, migration, re-authentication and the watchlist features."""

import time
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cineville import accounts as account_store
from custom_components.cineville.auth import Tokens
from custom_components.cineville.const import (
    CONF_ACCOUNT_NAME,
    CONF_ACCOUNTS,
    CONF_CITY_ID,
    CONF_CITY_NAME,
    CONF_EMAIL,
    CONF_TOKENS,
    CONF_USER_ID,
    DOMAIN,
    SERVICE_GET_PROGRAM,
)
from custom_components.cineville.exceptions import (
    CinevilleAuthError,
    CinevilleLoginPageError,
    CinevilleOtpError,
)
from ha_helpers import CLIENT, NOW, PRIMETIME, USER_2, USER_ID, account, mock_entry, showtimes

AUTH = "custom_components.cineville.auth.CinevilleAuth"
OTP = "custom_components.cineville.auth.OtpLogin"
WATCHLIST_SENSOR = "sensor.cineville_hamburg_watchlist_films_today"


@pytest.fixture
def api(freezer):
    """Cineville mocked: each account's lists come from these dicts (keyed by user ID)."""
    freezer.move_to(NOW)
    lists = {"watchlist": {USER_ID: {PRIMETIME, "other-film"}, USER_2: set()}, "seen": {USER_ID: set(), USER_2: set()}}
    userinfo = {"sub": USER_ID, "given_name": "Thorben", "name": "Thorben Grosser", "email": "thorben@example.org"}

    async def get_list(kind, self, user_id):
        error = lists.get(f"{kind}_error", {}).get(user_id)
        if error:
            raise error
        return set(lists[kind][user_id])

    async def watchlist(self, user_id):
        return await get_list("watchlist", self, user_id)

    async def seen(self, user_id):
        return await get_list("seen", self, user_id)

    with (
        patch(f"{CLIENT}.get_showtimes", AsyncMock(return_value=showtimes())),
        patch(f"{CLIENT}.get_watchlist_ids", watchlist),
        patch(f"{CLIENT}.get_seen_ids", seen),
        patch(f"{CLIENT}.get_userinfo", AsyncMock(side_effect=lambda: dict(userinfo))),
        patch(f"{AUTH}.exchange_code", AsyncMock(return_value=Tokens("new-access", "new-refresh", time.time() + 3600))) as exchange,
        patch(f"{AUTH}.revoke", AsyncMock()) as revoke,
        patch(f"{OTP}.start", AsyncMock()) as otp_start,
        patch(f"{OTP}.verify", AsyncMock(return_value="OAUTH-CODE")) as otp_verify,
    ):
        yield {"lists": lists, "userinfo": userinfo, "exchange": exchange, "revoke": revoke,
               "otp_start": otp_start, "otp_verify": otp_verify}


async def setup(hass: HomeAssistant, entry):
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def program(hass: HomeAssistant):
    return await hass.services.async_call(DOMAIN, SERVICE_GET_PROGRAM, {}, blocking=True, return_response=True)


async def options_step(hass: HomeAssistant, entry, step=None):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "account"})
    if step:
        result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": step})
    return result


async def email_login(hass: HomeAssistant, entry, email="thorben@example.org", otp="123456"):
    """Account menu -> Add an account -> email -> code."""
    result = await options_step(hass, entry, "login")
    assert result["step_id"] == "login"
    result = await hass.config_entries.options.async_configure(result["flow_id"], {CONF_EMAIL: email})
    assert result["step_id"] == "login_code", result.get("errors")
    assert result["description_placeholders"] == {"email": email.strip()}
    return await hass.config_entries.options.async_configure(result["flow_id"], {"code": otp})


# --- account store helpers ------------------------------------------------------------


def test_migrate_v1_with_account():
    tokens = {"access_token": "a", "refresh_token": "r", "expires_at": 1.0}
    v1 = {CONF_CITY_ID: "hamburg", CONF_CITY_NAME: "Hamburg", CONF_TOKENS: tokens, CONF_USER_ID: "u", CONF_ACCOUNT_NAME: "T"}
    assert account_store.migrate_v1(v1) == {
        CONF_CITY_ID: "hamburg", CONF_CITY_NAME: "Hamburg",
        CONF_ACCOUNTS: [{CONF_USER_ID: "u", CONF_ACCOUNT_NAME: "T", CONF_TOKENS: tokens}],
    }


def test_migrate_v1_without_account():
    assert account_store.migrate_v1({CONF_CITY_ID: "hamburg"}) == {CONF_CITY_ID: "hamburg", CONF_ACCOUNTS: []}


def test_display_name():
    assert account_store.display_name({"given_name": "Anna", "name": "Anna Berg"}) == "Anna"
    assert account_store.display_name({"name": "Anna Berg"}) == "Anna Berg"
    assert account_store.display_name({"email": "anna@example.org"}) == "anna"


async def test_v1_entry_is_migrated_on_setup(hass: HomeAssistant, api):
    tokens = {"access_token": "a", "refresh_token": "r", "expires_at": time.time() + 3600}
    entry = MockConfigEntry(
        domain=DOMAIN, version=1, unique_id="hamburg", title="Cineville Hamburg",
        data={CONF_CITY_ID: "hamburg", CONF_CITY_NAME: "Hamburg", CONF_TOKENS: tokens, CONF_USER_ID: USER_ID,
              CONF_ACCOUNT_NAME: "Thorben Grosser"},
        options={"venue_ids": []},
    )
    await setup(hass, entry)
    assert entry.version == 2
    assert entry.data[CONF_ACCOUNTS][0][CONF_USER_ID] == USER_ID
    assert CONF_TOKENS not in entry.data
    assert hass.states.get(WATCHLIST_SENSOR).state == "1"


# --- login / logout -------------------------------------------------------------------


async def test_login_with_email_and_code(hass: HomeAssistant, api):
    entry = await setup(hass, mock_entry())
    assert hass.states.get(WATCHLIST_SENSOR) is None  # nobody logged in yet

    result = await options_step(hass, entry)
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["login", "login_manual"]  # nothing to remove yet

    result = await email_login(hass, entry, " thorben@example.org ")
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    api["otp_start"].assert_awaited_once_with("thorben@example.org")
    api["otp_verify"].assert_awaited_once_with("123456")
    code, verifier = api["exchange"].await_args.args
    assert code == "OAUTH-CODE" and verifier
    [stored] = entry.data[CONF_ACCOUNTS]
    assert stored[CONF_USER_ID] == USER_ID
    assert stored[CONF_ACCOUNT_NAME] == "Thorben"  # first name, for the markers on the card
    assert stored[CONF_EMAIL] == "thorben@example.org"  # prefilled when re-authenticating
    assert stored[CONF_TOKENS]["refresh_token"] == "new-refresh"

    state = hass.states.get(WATCHLIST_SENSOR)
    assert state.state == "1"
    assert state.attributes["films"][0]["title"] == "Primetime"
    assert state.attributes["films"][0]["wanted_by"] == ["Thorben"]


async def test_wrong_code_can_be_retried(hass: HomeAssistant, api):
    entry = await setup(hass, mock_entry())
    api["otp_verify"].side_effect = [CinevilleOtpError("wrong"), "OAUTH-CODE"]
    result = await options_step(hass, entry, "login")
    result = await hass.config_entries.options.async_configure(result["flow_id"], {CONF_EMAIL: "thorben@example.org"})
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"code": "000000"})
    assert result["step_id"] == "login_code"
    assert result["errors"] == {"base": "invalid_otp"}
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"code": "123456"})
    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.parametrize(
    ("start_error", "expected"),
    [
        (CinevilleAuthError("unknown"), "invalid_email"),
        (CinevilleLoginPageError("changed"), "login_page_changed"),
    ],
)
async def test_email_step_errors(hass: HomeAssistant, api, start_error, expected):
    entry = await setup(hass, mock_entry())
    api["otp_start"].side_effect = start_error
    result = await options_step(hass, entry, "login")
    result = await hass.config_entries.options.async_configure(result["flow_id"], {CONF_EMAIL: "x@example.org"})
    assert result["step_id"] == "login"
    assert result["errors"] == {"base": expected}


async def test_second_account_is_added(hass: HomeAssistant, api):
    entry = await setup(hass, mock_entry(logged_in=True))
    result = await options_step(hass, entry)
    assert result["menu_options"] == ["login", "login_manual", "logout"]
    assert result["description_placeholders"] == {"names": "Thorben"}

    api["userinfo"].update(sub=USER_2, given_name="Anna", name="Anna Berg", email="anna@example.org")
    api["lists"]["watchlist"][USER_2] = {PRIMETIME}
    result = await email_login(hass, entry, "anna@example.org")
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    assert [a[CONF_ACCOUNT_NAME] for a in entry.data[CONF_ACCOUNTS]] == ["Thorben", "Anna"]
    response = await program(hass)
    assert response["accounts"] == [{"id": USER_ID, "name": "Thorben"}, {"id": USER_2, "name": "Anna"}]
    assert response["showtimes"][0]["film"]["watchlist_by"] == [USER_ID, USER_2]
    assert hass.states.get(WATCHLIST_SENSOR).attributes["films"][0]["wanted_by"] == ["Thorben", "Anna"]


async def test_logging_in_again_renews_instead_of_duplicating(hass: HomeAssistant, api):
    entry = await setup(hass, mock_entry(logged_in=True))
    await email_login(hass, entry)
    await hass.async_block_till_done()
    [stored] = entry.data[CONF_ACCOUNTS]
    assert stored[CONF_TOKENS]["access_token"] == "new-access"


async def test_manual_login_fallback(hass: HomeAssistant, api):
    entry = await setup(hass, mock_entry())
    result = await options_step(hass, entry, "login_manual")
    assert result["step_id"] == "login_manual"
    url = result["description_placeholders"]["url"]
    assert url.startswith("https://api.cineville.de/connect/authorize?") and "response_mode=form_post" in url

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"code": '<input type="hidden" name="code" value="THE-CODE-1" />'}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert api["exchange"].await_args.args[0] == "THE-CODE-1"
    assert entry.data[CONF_ACCOUNTS][0][CONF_USER_ID] == USER_ID


@pytest.mark.parametrize(
    ("pasted", "exchange_error", "expected"),
    [("not a code!", None, "invalid_code"), ("EXPIRED-CODE", CinevilleAuthError("invalid_grant"), "login_failed")],
)
async def test_manual_login_errors(hass: HomeAssistant, api, pasted, exchange_error, expected):
    entry = await setup(hass, mock_entry())
    api["exchange"].side_effect = exchange_error
    result = await options_step(hass, entry, "login_manual")
    first_url = result["description_placeholders"]["url"]
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"code": pasted})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}
    # A rejected code gets a fresh link (codes are single-use and bound to their verifier)
    assert (result["description_placeholders"]["url"] != first_url) == (expected == "login_failed")
    assert entry.data[CONF_ACCOUNTS] == []


async def test_remove_one_account(hass: HomeAssistant, api):
    entry = await setup(hass, mock_entry(accounts=[account(), account(USER_2, "Anna")]))
    result = await options_step(hass, entry, "logout")
    assert result["step_id"] == "logout"
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"remove": [USER_2]})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    api["revoke"].assert_awaited_once()
    assert [a[CONF_USER_ID] for a in entry.data[CONF_ACCOUNTS]] == [USER_ID]
    assert entry.state is ConfigEntryState.LOADED
    assert (await program(hass))["accounts"] == [{"id": USER_ID, "name": "Thorben"}]


# --- combined flags -------------------------------------------------------------------


async def test_seen_means_seen_by_everyone(hass: HomeAssistant, api):
    api["lists"]["watchlist"][USER_2] = {PRIMETIME}
    api["lists"]["seen"][USER_ID] = {PRIMETIME}
    await setup(hass, mock_entry(accounts=[account(), account(USER_2, "Anna")]))

    film = (await program(hass))["showtimes"][0]["film"]
    assert film["seen_by"] == [USER_ID]
    assert film["seen"] is False  # Anna hasn't seen it yet
    assert film["on_watchlist"] is True
    assert hass.states.get(WATCHLIST_SENSOR).state == "1"

    api["lists"]["seen"][USER_2] = {PRIMETIME}
    for coordinator in hass.config_entries.async_entries(DOMAIN)[0].runtime_data.accounts.values():
        await coordinator.async_refresh()
    await hass.async_block_till_done()
    film = (await program(hass))["showtimes"][0]["film"]
    assert film["seen"] is True
    assert hass.states.get(WATCHLIST_SENSOR).state == "0"


async def test_program_without_login(hass: HomeAssistant, api):
    await setup(hass, mock_entry())
    response = await program(hass)
    assert response["logged_in"] is False
    assert response["accounts"] == []
    film = response["showtimes"][0]["film"]
    assert film["on_watchlist"] is False and film["watchlist_by"] == [] and film["seen"] is False


# --- re-authentication ----------------------------------------------------------------


async def test_expired_login_reauths_that_account_only(hass: HomeAssistant, api):
    api["lists"]["watchlist_error"] = {USER_2: CinevilleAuthError("Unauthorized")}
    anna = account(USER_2, "Anna") | {CONF_EMAIL: "anna@example.org"}
    entry = await setup(hass, mock_entry(accounts=[account(), anna]))

    # The program and the other account keep working
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get("sensor.cineville_hamburg_upcoming_screenings_today").state == "2"
    assert (await program(hass))["accounts"] == [{"id": USER_ID, "name": "Thorben"}]

    [flow] = hass.config_entries.flow.async_progress()
    assert flow["context"]["source"] == config_entries.SOURCE_REAUTH
    result = await hass.config_entries.flow.async_configure(flow["flow_id"])
    assert result["step_id"] == "reauth_confirm"
    assert result["description_placeholders"]["name"] == "Anna"
    # Anna's email address is prefilled
    [field] = [k for k in result["data_schema"].schema if str(k) == CONF_EMAIL]
    assert field.description == {"suggested_value": "anna@example.org"}

    # Logging in as the wrong person is rejected and goes back to the email step
    result = await hass.config_entries.flow.async_configure(flow["flow_id"], {CONF_EMAIL: "thorben@example.org"})
    assert result["step_id"] == "reauth_code"
    result = await hass.config_entries.flow.async_configure(flow["flow_id"], {"code": "111111"})
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": "wrong_account"}

    api["userinfo"].update(sub=USER_2, given_name="Anna", email="anna@example.org")
    api["lists"]["watchlist_error"] = {}
    result = await hass.config_entries.flow.async_configure(flow["flow_id"], {CONF_EMAIL: "anna@example.org"})
    result = await hass.config_entries.flow.async_configure(flow["flow_id"], {"code": "222222"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    await hass.async_block_till_done()
    assert account_store.find(dict(entry.data), USER_2)[CONF_TOKENS]["access_token"] == "new-access"
    assert len((await program(hass))["accounts"]) == 2


async def test_reauth_falls_back_to_manual_when_the_login_page_changed(hass: HomeAssistant, api):
    api["lists"]["watchlist_error"] = {USER_ID: CinevilleAuthError("Unauthorized")}
    entry = await setup(hass, mock_entry(logged_in=True))
    [flow] = hass.config_entries.flow.async_progress()
    await hass.config_entries.flow.async_configure(flow["flow_id"])

    api["otp_start"].side_effect = CinevilleLoginPageError("changed")
    result = await hass.config_entries.flow.async_configure(flow["flow_id"], {CONF_EMAIL: "thorben@example.org"})
    assert result["step_id"] == "reauth_manual"
    assert result["description_placeholders"]["url"].startswith("https://api.cineville.de/connect/authorize?")

    api["lists"]["watchlist_error"] = {}
    result = await hass.config_entries.flow.async_configure(flow["flow_id"], {"code": "PASTED-CODE"})
    assert result["reason"] == "reauth_successful"
    await hass.async_block_till_done()
    assert entry.data[CONF_ACCOUNTS][0][CONF_TOKENS]["access_token"] == "new-access"
