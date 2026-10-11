"""Base entity for Cineville."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_CITY_NAME, DOMAIN, WEBSITE_URL
from .coordinator import CinevilleCoordinator


class CinevilleEntity(CoordinatorEntity[CinevilleCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: CinevilleCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"Cineville {entry.data[CONF_CITY_NAME]}",
            manufacturer="Cineville",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=f"{WEBSITE_URL}/de-DE/programm",
        )
