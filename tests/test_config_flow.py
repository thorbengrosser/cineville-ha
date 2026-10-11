from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.cineville.const import CONF_CITY_ID, CONF_CITY_NAME, CONF_VENUE_IDS, DOMAIN
from custom_components.cineville.exceptions import CinevilleConnectionError
from ha_helpers import CITIES, CLIENT, VENUES, mock_entry, showtimes


@pytest.fixture
def mock_client():
    with (
        patch(f"{CLIENT}.get_cities", AsyncMock(return_value=CITIES)) as cities,
        patch(f"{CLIENT}.get_venues", AsyncMock(return_value=VENUES)) as venues,
        patch(f"{CLIENT}.get_showtimes", AsyncMock(return_value=showtimes())),
    ):
        yield cities, venues


async def _start(hass: HomeAssistant):
    return await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})


async def test_full_flow_all_cinemas_means_whole_city(hass: HomeAssistant, mock_client):
    result = await _start(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_CITY_ID: "hamburg"})
    assert result["step_id"] == "venues"
    assert result["description_placeholders"] == {"city": "Hamburg"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_VENUE_IDS: [v.id for v in VENUES]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Cineville Hamburg"
    assert result["data"] == {CONF_CITY_ID: "hamburg", CONF_CITY_NAME: "Hamburg"}
    assert result["options"] == {CONF_VENUE_IDS: []}
    mock_client[1].assert_awaited_once_with("hamburg")


async def test_flow_with_some_cinemas(hass: HomeAssistant, mock_client):
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_CITY_ID: "hamburg"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_VENUE_IDS: ["v-studio"]})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"] == {CONF_VENUE_IDS: ["v-studio"]}


async def test_no_cinema_selected_shows_error(hass: HomeAssistant, mock_client):
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_CITY_ID: "hamburg"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_VENUE_IDS: []})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_VENUE_IDS: "no_venues_selected"}


async def test_cannot_connect_then_recover(hass: HomeAssistant, mock_client):
    mock_client[0].side_effect = CinevilleConnectionError("down")
    result = await _start(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}

    mock_client[0].side_effect = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "user"
    assert result["errors"] == {}


async def test_city_already_configured(hass: HomeAssistant, mock_client):
    mock_entry().add_to_hass(hass)
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_CITY_ID: "hamburg"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_flow_changes_cinemas(hass: HomeAssistant, mock_client):
    entry = mock_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["venues", "account"]
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "venues"})
    assert result["step_id"] == "venues"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_VENUE_IDS: ["v-abaton", "v-zeise"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options[CONF_VENUE_IDS] == ["v-abaton", "v-zeise"]
