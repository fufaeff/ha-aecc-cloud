"""AECC Cloud select platform."""
from __future__ import annotations

import logging
import time
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .hub import (
    CHARGE_PRIORITY_FIELD,
    OUTPUT_PRIORITY_FIELD,
    charge_priority_code,
    output_priority_code,
)

_LOGGER = logging.getLogger(__name__)

# Hold the user's choice this long after a successful write: the inverter
# uploads telemetry every 5 minutes, so the old value may still be reported.
SELECT_HOLD_SEC = 360

# Output Priority (inverter register 0x4102)
MODE_SBU = "SBU (Solar -> Battery -> Utility)"   # PBG
MODE_SUB = "SUB (Solar -> Utility -> Battery)"   # PGB
MODE_USB = "USB (Utility -> Solar -> Battery)"   # GPB
# MKS: generator powers loads first; with generator + PV + battery the inverter
# behaves as PBG, with generator + PV or battery only it behaves as GPB.
MODE_MKS = "MKS (Generator first)"

MODE_OPTIONS = [MODE_SBU, MODE_SUB, MODE_USB, MODE_MKS]
MODE_BY_CODE = {"PBG": MODE_SBU, "PGB": MODE_SUB, "GPB": MODE_USB, "MKS": MODE_MKS}

# Charging Priority (inverter register 0x4104)
CHARGER_PRIORITY_CSO = "CSO (Solar first / Приоритет солнце)"        # PVF
CHARGER_PRIORITY_SNU = "SNU (Solar and Utility / Солнце и сеть)"     # PNG
CHARGER_PRIORITY_OSO = "OSO (Only Solar / Только солнце)"            # OPV

CHARGER_PRIORITY_OPTIONS = [
    CHARGER_PRIORITY_CSO,
    CHARGER_PRIORITY_SNU,
    CHARGER_PRIORITY_OSO,
]
CHARGER_BY_CODE = {"PVF": CHARGER_PRIORITY_CSO, "PNG": CHARGER_PRIORITY_SNU, "OPV": CHARGER_PRIORITY_OSO}


def _current_code(devices_info: dict, display_keys: tuple, parse, hub, field: str, device_sn: str):
    """Current setting code: inverter telemetry (displayMap) first, settings template second."""
    for mp in (devices_info or {}).values():
        if isinstance(mp, dict):
            for key in display_keys:
                if mp.get(key):
                    code = parse(mp.get(key))
                    if code:
                        return code
    choice = hub.get_setting_choice(field, device_sn)
    return parse(choice) if choice else None


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up AECC Cloud select platform from config entry."""
    device_manager = hass.data.get(DOMAIN, {}).get("device_manager")
    if device_manager:
        selects = device_manager.entities.get("select", [])
        async_add_entities(selects)
        _LOGGER.info(f"Loaded {len(selects)} AECC Cloud select entities")


class AeccWorkingModeSelect(SelectEntity):
    """AECC Cloud Inverter Working Mode selector (SBU / SUB / USB)."""

    def __init__(self, hass: HomeAssistant, hub, device):
        """Initialize the working mode select entity."""
        super().__init__()
        self.hass = hass
        self.hub = hub
        self.device = device
        self.pf = "select"
        self._name = "Working Mode"
        self._key = "working_mode"
        self._unique_id = f"aecc_{self.device.device_sn}_working_mode"
        self._current_option = MODE_SBU
        self._attr_options = MODE_OPTIONS
        self._last_user_select_time: float = 0
        self._available = True

        hub.add_entity(self)

    @property
    def unique_id(self) -> str:
        return self._unique_id

    @property
    def name(self) -> str:
        return f"{self.device.device_name or self.device.device_sn} Working Mode"

    @property
    def current_option(self) -> str:
        return self._current_option

    @property
    def options(self) -> list[str]:
        return self._attr_options

    @property
    def icon(self) -> str:
        if self._current_option == MODE_MKS:
            return "mdi:engine"
        if self._current_option == MODE_USB:
            return "mdi:power-plug-battery"
        if self._current_option == MODE_SUB:
            return "mdi:solar-power"
        return "mdi:home-battery"

    @property
    def available(self) -> bool:
        return self._available

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, str(self.device.device_sn))},
            "name": str(self.device.device_name or self.device.device_sn),
            "model": str(self.device.icon_type) if self.device.icon_type is not None else "AECC Energy Hub",
            "manufacturer": "AECC",
        }

    def select_option(self, option: str) -> None:
        """Change the selected working mode synchronously."""
        import asyncio
        asyncio.run_coroutine_threadsafe(self.async_select_option(option), self.hass.loop).result()

    async def async_select_option(self, option: str) -> None:
        """Change the selected working mode."""
        if option not in self._attr_options:
            _LOGGER.warning(f"[AECC Working Mode] Invalid mode selected: {option}")
            return

        _LOGGER.info(f"[AECC Working Mode] User selected option: {option}")
        success = await self.hub.set_working_mode(option, device_sn=self.device.device_sn)
        if not success:
            raise HomeAssistantError(f"AEC Cloud rejected Output Priority '{option}'")

        self._current_option = option
        self._last_user_select_time = time.time()
        self.async_write_ha_state()

    def update_data(self, new_data: dict, devices_info: dict, ai: dict):
        """Update select state from inverter telemetry / settings."""
        if time.time() - self._last_user_select_time < SELECT_HOLD_SEC:
            return
        code = _current_code(
            devices_info, ("Output Priority", "output_priority"), output_priority_code,
            self.hub, OUTPUT_PRIORITY_FIELD, self.device.device_sn,
        )
        if code in MODE_BY_CODE:
            self._current_option = MODE_BY_CODE[code]
        self.async_write_ha_state()


class AeccPlantSelect(SelectEntity):
    """AECC Cloud Active Plant selector."""

    def __init__(self, hass: HomeAssistant, hub, device):
        """Initialize the plant select entity."""
        super().__init__()
        self.hass = hass
        self.hub = hub
        self.device = device
        self.pf = "select"
        self._name = "Active Plant"
        self._key = "active_plant"
        self._unique_id = f"aecc_{self.device.device_sn}_active_plant"
        self._available = True
        self._attr_icon = "mdi:solar-power"

        cur_name = self.hass.data.get(DOMAIN, {}).get("cur_plant_name") or str(self.hub.senceId)
        self._current_option = cur_name
        self._attr_options = [cur_name]

        hub.add_entity(self)

    @property
    def unique_id(self) -> str:
        return self._unique_id

    @property
    def name(self) -> str:
        return f"{self.device.device_name or self.device.device_sn} Active Plant"

    @property
    def current_option(self) -> str:
        return self._current_option

    @property
    def options(self) -> list[str]:
        return self._attr_options

    @property
    def available(self) -> bool:
        return self._available

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, str(self.device.device_sn))},
            "name": str(self.device.device_name or self.device.device_sn),
            "model": str(self.device.icon_type) if self.device.icon_type is not None else "AECC Energy Hub",
            "manufacturer": "AECC",
        }

    async def async_select_option(self, option: str) -> None:
        """Switch active monitored plant."""
        _LOGGER.info(f"Switching active plant to: {option}")
        plant_id = None
        for p in self.hub.plants or []:
            name = p.get("plantName") or p.get("name") or str(p.get("id"))
            if name == option:
                plant_id = p.get("id")
                break

        if plant_id is None:
            plant_id = option

        self.hub.senceId = str(plant_id)
        self.hass.data.setdefault(DOMAIN, {})["cur_plant_name"] = str(option)
        self._current_option = option
        self.async_write_ha_state()

        await self.hub.async_update_data()

    def update_data(self, new_data: dict, devices_info: dict, ai: dict):
        """Update options list from known plants."""
        plants = self.hub.plants or []
        opts = []
        for p in plants:
            name = p.get("plantName") or p.get("name") or str(p.get("id"))
            if name and name not in opts:
                opts.append(name)

        cur_name = self.hass.data.get(DOMAIN, {}).get("cur_plant_name")
        if cur_name and cur_name not in opts:
            opts.insert(0, cur_name)

        if opts:
            self._attr_options = opts

        if cur_name and cur_name in self._attr_options:
            self._current_option = cur_name

        self.async_write_ha_state()


class AeccChargerPrioritySelect(SelectEntity):
    """AECC Cloud Inverter Charger Source Priority selector (CSO / SNU / OSO / CUT)."""

    def __init__(self, hass: HomeAssistant, hub, device):
        """Initialize the charger source priority select entity."""
        super().__init__()
        self.hass = hass
        self.hub = hub
        self.device = device
        self.pf = "select"
        self._name = "Charger Source Priority"
        self._key = "charger_source_priority"
        self._unique_id = f"aecc_{self.device.device_sn}_charger_source_priority"
        self._current_option = CHARGER_PRIORITY_CSO
        self._attr_options = CHARGER_PRIORITY_OPTIONS
        self._last_user_select_time: float = 0
        self._available = True

        hub.add_entity(self)

    @property
    def unique_id(self) -> str:
        return self._unique_id

    @property
    def name(self) -> str:
        return f"{self.device.device_name or self.device.device_sn} Charger Source Priority"

    @property
    def current_option(self) -> str:
        return self._current_option

    @property
    def options(self) -> list[str]:
        return self._attr_options

    @property
    def icon(self) -> str:
        if self._current_option == CHARGER_PRIORITY_OSO:
            return "mdi:solar-power-variant"
        if self._current_option == CHARGER_PRIORITY_SNU:
            return "mdi:transmission-tower-export"
        return "mdi:battery-charging-high"

    @property
    def available(self) -> bool:
        return self._available

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, str(self.device.device_sn))},
            "name": str(self.device.device_name or self.device.device_sn),
            "model": str(self.device.icon_type) if self.device.icon_type is not None else "AECC Energy Hub",
            "manufacturer": "AECC",
        }

    def select_option(self, option: str) -> None:
        """Change the selected charger priority mode synchronously."""
        import asyncio
        asyncio.run_coroutine_threadsafe(self.async_select_option(option), self.hass.loop).result()

    async def async_select_option(self, option: str) -> None:
        """Change the selected charger priority mode."""
        if option not in self._attr_options:
            _LOGGER.warning(f"[AECC Charger Priority] Invalid charger priority mode selected: {option}")
            return

        _LOGGER.info(f"[AECC Charger Priority] User selected option: {option}")
        success = await self.hub.set_charger_priority(option, device_sn=self.device.device_sn)
        if not success:
            raise HomeAssistantError(f"AEC Cloud rejected Charging Priority '{option}'")

        self._current_option = option
        self._last_user_select_time = time.time()
        self.async_write_ha_state()

    def update_data(self, new_data: dict, devices_info: dict, ai: dict):
        """Update select state from inverter telemetry / settings."""
        if time.time() - self._last_user_select_time < SELECT_HOLD_SEC:
            return
        code = _current_code(
            devices_info,
            ("Charging Priority", "charging_priority", "Charger Priority", "charger_priority"),
            charge_priority_code,
            self.hub, CHARGE_PRIORITY_FIELD, self.device.device_sn,
        )
        if code in CHARGER_BY_CODE:
            self._current_option = CHARGER_BY_CODE[code]
        self.async_write_ha_state()


# Extra list-type inverter settings exposed as selects: (fieldName, name, icon).
# Destructive or wiring-dependent items (factory reset, clear statistics,
# battery type, BMS protocol) are deliberately not exposed.
SETTING_SELECTS = [
    ("mainsChargeCurrent", "Mains Charging Current", "mdi:current-ac"),
    ("maxChargeCurrent2", "Maximum Charging Current", "mdi:battery-charging-high"),
    ("buzzerSilence", "Mute Buzzer", "mdi:volume-off"),
]


class AeccSettingSelect(SelectEntity):
    """Generic list-type inverter setting from /deviceSetConfig/getSettingInfo."""

    _attr_should_poll = False

    def __init__(self, hub, device, field: str, name: str, icon: str):
        super().__init__()
        self.hub = hub
        self.device = device
        self.pf = "select"
        self._field = field
        self._attr_name = f"{device.device_name or device.device_sn} {name}"
        self._attr_unique_id = f"aecc_{device.device_sn}_setting_{field.lower()}"
        self._attr_icon = icon
        self._attr_options = []
        self._attr_current_option = None
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
        choices = ((item or {}).get("componentObj") or {}).get("choiceParamArr") or []
        self._attr_options = [str(c.get("name")) for c in choices]
        self._attr_current_option = self.hub.get_setting_choice(self._field, self.device.device_sn)
        self._attr_available = bool(self._attr_options)

    async def async_added_to_hass(self) -> None:
        self._refresh()

    async def async_select_option(self, option: str) -> None:
        if not await self.hub.set_custom_param(self._field, option, device_sn=self.device.device_sn):
            raise HomeAssistantError(f"AEC Cloud rejected {self.name} = {option}")
        self._refresh()
        self.async_write_ha_state()

    def update_data(self, new_data: dict, devices_info: dict, ai: dict):
        self._refresh()
        if self.platform is not None:
            self.async_write_ha_state()
