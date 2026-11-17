"""AECC Cloud number platform: numeric inverter settings (via /deviceSetConfig)."""
from __future__ import annotations

import logging
from typing import Optional

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# (fieldName, name, unit, min, max, icon) - ranges as shown by the AECC app
SETTING_NUMBERS = [
    ("transferMainsSoc", "SOC for Switching to Mains", PERCENTAGE, 10, 90, "mdi:transmission-tower-import"),
    ("transferBatterySoc", "SOC for Switching to Battery", PERCENTAGE, 10, 100, "mdi:home-battery"),
    ("lowSocShutdownSoc", "Low SOC Shutdown", PERCENTAGE, 5, 50, "mdi:battery-alert-variant-outline"),
]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up AECC Cloud number platform from config entry."""
    numbers = hass.data[DOMAIN][config_entry.entry_id].device_manager.entities.get("number", [])
    async_add_entities(numbers)
    _LOGGER.info(f"Loaded {len(numbers)} AECC Cloud number entities")


class AeccSettingNumber(NumberEntity):
    """Generic numeric inverter setting from /deviceSetConfig/getSettingInfo."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_mode = NumberMode.BOX
    _attr_native_step = 1

    def __init__(self, hub, device, field: str, name: str, unit: str, vmin: float, vmax: float, icon: str):
        super().__init__()
        self.hub = hub
        self.device = device
        self.pf = "number"
        self._field = field
        self._attr_name = name
        self._attr_unique_id = f"aecc_{device.device_sn}_setting_{field.lower()}"
        self._attr_native_unit_of_measurement = unit
        self._attr_native_min_value = vmin
        self._attr_native_max_value = vmax
        self._attr_icon = icon
        self._attr_native_value = None
        self._attr_available = False
        hub.add_entity(self)

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, str(self.device.device_sn))},
            "name": str(self.device.device_name or self.device.device_sn),
            "model": str(self.device.icon_type) if self.device.icon_type is not None else "AECC Energy Hub",
            "manufacturer": "AECC",
        }

    def _refresh(self) -> None:
        item = self.hub.get_setting_item(self._field, self.device.device_sn)
        self._attr_available = item is not None
        value: Optional[float] = None
        try:
            value = float((item or {}).get("cellVal"))
        except (TypeError, ValueError):
            value = None
        # Out-of-range values (e.g. 65521 = "not set") are shown as unknown
        if value is not None and not (self.native_min_value <= value <= self.native_max_value):
            value = None
        self._attr_native_value = value

    async def async_added_to_hass(self) -> None:
        self._refresh()

    async def async_set_native_value(self, value: float) -> None:
        text = str(int(round(value)))
        if not await self.hub.set_custom_value(self._field, text, device_sn=self.device.device_sn):
            raise HomeAssistantError(f"AEC Cloud rejected {self.name} = {text}")
        self._refresh()
        self.async_write_ha_state()

    def update_data(self, new_data: dict, devices_info: dict, ai: dict):
        self._refresh()
        if self.platform is not None:
            self.async_write_ha_state()
