from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant

from custom_components.cineville import CARD_FILE, CARD_URL_PATH, _async_register_card

CARD = Path(__file__).resolve().parent.parent / "custom_components" / "cineville" / "frontend" / CARD_FILE


async def test_card_is_served_and_auto_loaded(hass: HomeAssistant):
    hass.http = MagicMock(async_register_static_paths=AsyncMock())
    hass.config.components.add("frontend")
    with patch("homeassistant.components.frontend.add_extra_js_url") as add_js:
        await _async_register_card(hass)

    (configs,), _ = hass.http.async_register_static_paths.await_args
    assert configs[0].url_path == CARD_URL_PATH
    assert Path(configs[0].path) == CARD.parent
    url = add_js.call_args.args[1]
    assert url.startswith(f"{CARD_URL_PATH}/{CARD_FILE}?v=")


async def test_card_skipped_without_frontend(hass: HomeAssistant):
    hass.http = MagicMock(async_register_static_paths=AsyncMock())
    with patch("homeassistant.components.frontend.add_extra_js_url") as add_js:
        await _async_register_card(hass)
    hass.http.async_register_static_paths.assert_not_awaited()
    add_js.assert_not_called()


def test_card_file_exists_and_defines_element():
    source = CARD.read_text()
    assert 'customElements.define("cineville-card"' in source
    assert '"get_program"' in source
