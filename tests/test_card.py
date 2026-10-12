from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.cineville import CARD_FILE, CARD_URL_PATH, _async_register_card, async_remove_entry
from ha_helpers import mock_entry

CARD = Path(__file__).resolve().parent.parent / "custom_components" / "cineville" / "frontend" / CARD_FILE
CARD_URL = f"{CARD_URL_PATH}/{CARD_FILE}"


class FakeResources:
    """Stands in for lovelace's ResourceStorageCollection (the list under Settings → Dashboards → Resources)."""

    def __init__(self, items=None):
        self.items = {i["id"]: i for i in (items or [])}
        self.loaded = False

    async def async_get_info(self):
        self.loaded = True
        return {"resources": len(self.items)}

    def async_items(self):
        assert self.loaded, "collection used before loading"
        return list(self.items.values())

    async def async_create_item(self, data):
        item = {"id": f"id{len(self.items) + 1}", "type": data["res_type"], "url": data["url"]}
        self.items[item["id"]] = item
        return item

    async def async_update_item(self, item_id, updates):
        self.items[item_id] = {**self.items[item_id], "type": updates["res_type"], "url": updates["url"]}

    async def async_delete_item(self, item_id):
        del self.items[item_id]


@dataclass
class FakeLovelace:
    resource_mode: str = "storage"
    resources: FakeResources = field(default_factory=FakeResources)


@pytest.fixture
def frontend(hass: HomeAssistant):
    hass.http = MagicMock(async_register_static_paths=AsyncMock())
    hass.config.components.add("frontend")
    with patch("homeassistant.components.frontend.add_extra_js_url") as add_js:
        yield add_js


async def test_card_is_served_and_registered_as_resource(hass: HomeAssistant, frontend):
    lovelace = FakeLovelace(resources=FakeResources([{"id": "other", "type": "module", "url": "/hacsfiles/x.js"}]))
    hass.data["lovelace"] = lovelace
    await _async_register_card(hass)

    (configs,), _ = hass.http.async_register_static_paths.await_args
    assert configs[0].url_path == CARD_URL_PATH
    assert Path(configs[0].path) == CARD.parent
    [card] = [i for i in lovelace.resources.items.values() if i["url"].startswith(CARD_URL)]
    assert card["type"] == "module"
    assert card["url"].startswith(f"{CARD_URL}?v=")
    assert "other" in lovelace.resources.items  # other resources untouched
    frontend.assert_not_called()  # no second, racing load


async def test_outdated_resource_is_updated_and_duplicates_removed(hass: HomeAssistant, frontend):
    lovelace = FakeLovelace(resources=FakeResources([
        {"id": "a", "type": "module", "url": f"{CARD_URL}?v=0.1.0"},
        {"id": "b", "type": "js", "url": f"{CARD_URL}?v=0.0.9"},
    ]))
    hass.data["lovelace"] = lovelace
    await _async_register_card(hass)
    assert list(lovelace.resources.items) == ["a"]
    assert lovelace.resources.items["a"]["url"] != f"{CARD_URL}?v=0.1.0"
    assert lovelace.resources.items["a"]["url"].startswith(f"{CARD_URL}?v=")


async def test_yaml_resources_fall_back_to_extra_js(hass: HomeAssistant, frontend):
    hass.data["lovelace"] = FakeLovelace(resource_mode="yaml")
    await _async_register_card(hass)
    url = frontend.call_args.args[1]
    assert url.startswith(f"{CARD_URL}?v=")


async def test_card_skipped_without_frontend(hass: HomeAssistant):
    hass.http = MagicMock(async_register_static_paths=AsyncMock())
    with patch("homeassistant.components.frontend.add_extra_js_url") as add_js:
        await _async_register_card(hass)
    hass.http.async_register_static_paths.assert_not_awaited()
    add_js.assert_not_called()


async def test_resource_removed_with_the_last_entry(hass: HomeAssistant):
    lovelace = FakeLovelace(resources=FakeResources([
        {"id": "a", "type": "module", "url": f"{CARD_URL}?v=0.5.0"},
        {"id": "other", "type": "module", "url": "/hacsfiles/x.js"},
    ]))
    hass.data["lovelace"] = lovelace
    entry = mock_entry()
    entry.add_to_hass(hass)
    await async_remove_entry(hass, entry)
    assert list(lovelace.resources.items) == ["other"]


def test_card_file_exists_and_defines_element():
    source = CARD.read_text()
    assert 'customElements.define("cineville-card"' in source
    assert '"get_program"' in source
