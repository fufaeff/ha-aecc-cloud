import asyncio
import logging
import re
import time
from datetime import datetime
from typing import Any, Optional

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
import voluptuous as vol

from homeassistant.const import UnitOfEnergy, UnitOfPower
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_platform
from homeassistant.helpers.restore_state import RestoreEntity
from .hub import MyIntegrationHub
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SERVICE_SET_ENERGY = "set_energy_counter"


async def _async_handle_set_energy(entity, call) -> None:
    """Dispatch set_energy_counter only to calculated energy sensors."""
    if not isinstance(entity, AeccCalculatedEnergySensor):
        raise HomeAssistantError(f"{entity.entity_id} is not a calculated energy sensor")
    await entity.async_set_energy(call.data.get("value", 0.0))


def split_value_unit(s):
    """
    Split strings like '239kwh', '953w' or plain numbers ('123') into value and unit.
    :param s: Input string
    :return: (value: float, unit: str)
    """
    if s is None or s == '':
        return 0.0, ''

    pattern = r'^(-?\d+\.?\d*)\s*(\D*)$'
    match = re.fullmatch(pattern, str(s).strip())

    if not match:
        try:
            return float(s), ''
        except (ValueError, TypeError):
            return 0.0, ''

    try:
        value = float(match.group(1))
    except (ValueError, TypeError):
        value = 0.0

    unit = match.group(2).strip()
    return value, unit


_UNIT_NORMALIZE = {"w": "W", "kw": "kW", "kwh": "kWh", "wh": "Wh", "v": "V", "a": "A", "hz": "Hz"}


def parse_reading(value):
    """Parse a cloud reading into (state, unit).

    '953w' -> (953, 'W'), '12.5kwh' -> (12.5, 'kWh'), 42 -> (42, ''),
    'GPB' / 'Platova' / '2026-02-26 20:56' -> (text, '') - text is kept as is.
    """
    if isinstance(value, bool):
        return value, ""
    if isinstance(value, (int, float)):
        return value, ""
    text = str(value).strip()
    match = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*([^\d\s]*)", text)
    if not match:
        return text, ""
    num = match.group(1)
    unit = match.group(2)
    return (float(num) if "." in num else int(num)), _UNIT_NORMALIZE.get(unit.lower(), unit)


def total_load_power(data: dict) -> float:
    """Total consumption in W.

    homePower and loadPower describe the same load (the cloud reports identical
    values for both), so they must not be summed. Use the larger of the two and
    add EV charger power on top.
    """
    home_p = split_value_unit(data.get("homePower", 0))[0] or 0.0
    load_p = split_value_unit(data.get("loadPower", 0))[0] or 0.0
    charger_p = split_value_unit(data.get("chargerTotalPower", 0))[0] or 0.0
    return max(0.0, max(home_p, load_p) + charger_p)


class AeccSensor(SensorEntity):
    """AECC Cloud sensor entity."""

    def __init__(self, hub: MyIntegrationHub, device, name: str, key: str, unit: str = None):
        super().__init__()
        self.device = device
        self.hub = hub
        self.pf = "sensor"
        self._key = key
        self._name = name
        self._unique_id = self._generate_unique_id()
        self._unit = unit
        self._state = None
        self._attributes = {}
        if name == 'plant_name':
            self._attributes = {
                "data": hub.total_data,
                "devices": hub.device_data,
                "plants": hub.plants,
            }
        _LOGGER.debug(f"Created sensor entity: {self._name}, key={self._key}")
        # Register entity with hub for bulk polling updates
        hub.add_entity(self)

    def _generate_unique_id(self) -> str:
        device_sn = re.sub(r"[^a-z0-9]", "", self.device.device_sn.lower())
        key = self._key.replace('_', ' ').lower()
        return f"aecc_{device_sn}_{key}"

    @property
    def unique_id(self) -> str:
        return self._unique_id

    @property
    def name(self) -> str:
        return f"{self._name}"

    @property
    def native_value(self):
        return self._state

    @property
    def native_unit_of_measurement(self):
        return self._unit if self._unit else None

    @property
    def device_class(self) -> Optional[SensorDeviceClass]:
        if self._unit == "W":
            return SensorDeviceClass.POWER
        if self._unit in ("kWh", "kwh", "Wh", "wh"):
            return SensorDeviceClass.ENERGY
        if self._unit == "%":
            return SensorDeviceClass.BATTERY
        return None

    @property
    def state_class(self) -> Optional[SensorStateClass]:
        if self._unit == "W":
            return SensorStateClass.MEASUREMENT
        if self._unit in ("kWh", "kwh", "Wh", "wh"):
            return SensorStateClass.TOTAL
        if self._unit == "%":
            return SensorStateClass.MEASUREMENT
        return None

    @property
    def extra_state_attributes(self):
        return self._attributes

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, str(self.device.device_sn))},
            "name": str(self.device.device_name or self.device.device_sn),
            "model": str(self.device.icon_type) if self.device.icon_type is not None else "AECC Energy Hub",
            "manufacturer": "AECC",
        }

    def _apply_reading(self, value) -> None:
        """Set state/unit from a raw reading, keeping the configured unit if the value has none."""
        state, unit = parse_reading(value)
        if isinstance(state, str):
            # Text on a numeric sensor (e.g. '--') would be rejected by HA: report unknown
            self._state = None if self._unit else state
            return
        self._state = state
        if unit:
            self._unit = unit

    def update_data(self, new_data: dict, device_info: dict, ai: dict):
        """Update sensor value and attributes from telemetry payload."""
        v = new_data.get(self._key)

        if self._key == "aiSystemStatus":
            if ai and ai.get('antiRefluxSet') == 1:
                if ai.get('powerTimeSetVos'):
                    match ai['powerTimeSetVos'][0].get('mode'):
                        case 0:
                            self._state = "Peak"
                        case 1:
                            self._state = "Valley"
                        case 2:
                            self._state = "Negative Price"
                        case 3:
                            self._state = "Smart Linkage"
                        case 4:
                            self._state = "Guardian Mode"
                elif ai.get('powerMode') == 1:
                    self._state = "Zero Feed-in"
                elif ai.get('powerMode') == 0:
                    self._state = "Smart Linkage"
            else:
                self._state = "Off"
            self._unit = ""

        elif self._key == "plant_name":
            self._state = self.hass.data[DOMAIN].get('cur_plant_name', '')
            self._unit = ""

        else:
            if v is not None:
                self._apply_reading(v)

                if self._key == "totalLoadPower":
                    self._state = total_load_power(new_data)
                    self._unit = "W"

                # Battery power orientation based on batWorkMode
                if self._key == "batPower":
                    bat_p = split_value_unit(new_data.get("batPower", 0))[0] or 0
                    work_mode = new_data.get("batWorkMode", 1)
                    self._state = -(bat_p * work_mode)
                    self._unit = "W"

            else:
                # Fallback to sub-device info if not in top-level new_data
                for k, mp in device_info.items():
                    if self._key.startswith(k):
                        val = mp.get(self._name)
                        if val:
                            self._apply_reading(val)
                        elif self._key.endswith("device_name"):
                            self._state = self.device.device_name
                        break
                else:
                    self._state = 0

        # Construct attributes
        if self.device:
            attrs = {
                "deviceSn": self.device.device_sn,
                "iconType": self.device.icon_type,
                "dtc": self.device.device_code_type,
                "plantId": self.hub.senceId,
            }
        else:
            attrs = {
                "plantId": self.hub.senceId,
            }

        if self._key == "plant_name":
            self._attributes = {
                "last_updated": datetime.now().isoformat(),
                "data": self.hub.total_data,
                "devices": self.hub.device_data,
                "plants": self.hub.plants,
                "attrs": attrs,
            }
        else:
            self._attributes = {
                "last_updated": datetime.now().isoformat(),
                "attrs": attrs,
            }

        if not hasattr(self, "hass") or self.hass is None:
            _LOGGER.debug("Entity not initialized yet, skipping state write")
            return

        self.async_write_ha_state()


class AeccCalculatedEnergySensor(AeccSensor, RestoreEntity):
    """Calculated energy sensor (kWh) integrated from instantaneous power (W) via Left Riemann sum."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 3

    def __init__(self, hub: MyIntegrationHub, device, name: str, key: str, power_type: str):
        super().__init__(hub, device, name, key, UnitOfEnergy.KILO_WATT_HOUR)
        self._power_type = power_type
        self._total_energy = 0.0
        self._state = 0.0
        self._last_time: Optional[float] = None
        self._last_power: float = 0.0
        self._attributes = {
            "source_power_w": 0.0,
            "plantId": getattr(self.hub, "senceId", ""),
        }
        _LOGGER.info("Registered calculated energy sensor: %s (unique_id=%s)", self._name, self._unique_id)

    def _generate_unique_id(self) -> str:
        device_sn = re.sub(r"[^a-z0-9_]", "", str(self.device.device_sn).lower())
        key = re.sub(r"[^a-z0-9_]", "", self._key.lower())
        return f"aecc_{device_sn}_{key}"

    @property
    def should_poll(self) -> bool:
        return False

    @property
    def native_unit_of_measurement(self) -> str:
        return UnitOfEnergy.KILO_WATT_HOUR

    @property
    def device_class(self) -> SensorDeviceClass:
        return SensorDeviceClass.ENERGY

    @property
    def state_class(self) -> SensorStateClass:
        return SensorStateClass.TOTAL_INCREASING

    @property
    def native_value(self) -> Optional[float]:
        return round(self._total_energy, 3)

    @property
    def state(self) -> Optional[float]:
        return round(self._total_energy, 3)

    @property
    def extra_state_attributes(self) -> dict:
        return self._attributes

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, str(self.device.device_sn))},
            "name": str(self.device.device_name or self.device.device_sn),
            "model": str(self.device.icon_type) if self.device.icon_type is not None else "AECC Energy Hub",
            "manufacturer": "AECC",
        }

    async def async_added_to_hass(self):
        """Restore previous energy state upon Home Assistant startup."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in (None, "unknown", "unavailable"):
            try:
                self._total_energy = float(last_state.state)
                self._state = round(self._total_energy, 3)
                _LOGGER.info(
                    "Restored previous energy state for %s: %s kWh",
                    self._unique_id,
                    self._total_energy,
                )
            except (ValueError, TypeError):
                self._total_energy = 0.0
                self._state = 0.0
        else:
            self._state = round(self._total_energy, 3)

        self._last_time = time.monotonic()
        if hasattr(self, "hass") and self.hass is not None:
            self.async_write_ha_state()

    def update_data(self, new_data: dict, device_info: dict, ai: dict):
        """Update energy accumulation based on incoming power data using Left Riemann sum."""
        if not new_data:
            return

        current_power = 0.0
        try:
            if self._power_type == "total_load":
                current_power = total_load_power(new_data)
            elif self._power_type == "solar":
                solar_p = split_value_unit(new_data.get("solarPower", 0))[0]
                current_power = max(0.0, float(solar_p))
            elif self._power_type == "battery_charge":
                bat_p = abs(float(split_value_unit(new_data.get("batPower", 0))[0]))
                try:
                    work_mode = float(split_value_unit(new_data.get("batWorkMode", 0))[0])
                except (ValueError, TypeError):
                    work_mode = 0.0
                if work_mode > 0:
                    current_power = bat_p
                elif work_mode < 0:
                    current_power = 0.0
                else:
                    raw_val = float(split_value_unit(new_data.get("batPower", 0))[0])
                    current_power = max(0.0, raw_val)
            elif self._power_type == "battery_discharge":
                bat_p = abs(float(split_value_unit(new_data.get("batPower", 0))[0]))
                try:
                    work_mode = float(split_value_unit(new_data.get("batWorkMode", 0))[0])
                except (ValueError, TypeError):
                    work_mode = 0.0
                if work_mode < 0:
                    current_power = bat_p
                elif work_mode > 0:
                    current_power = 0.0
                else:
                    raw_val = float(split_value_unit(new_data.get("batPower", 0))[0])
                    current_power = max(0.0, -raw_val)
            else:
                val = split_value_unit(new_data.get(self._key, 0))[0]
                current_power = max(0.0, float(val))
        except Exception as err:
            _LOGGER.warning("Error calculating current power for %s: %s", self._name, err)
            current_power = 0.0

        now = time.monotonic()
        if self._last_time is not None:
            delta_t = now - self._last_time
            # Guard: 0 < delta_t <= 3600 seconds (prevents spikes if HA was offline)
            if 0 < delta_t <= 3600:
                delta_energy = (self._last_power * delta_t) / 3600000.0
                self._total_energy += delta_energy
                self._state = round(self._total_energy, 3)

        self._last_time = now
        self._last_power = current_power

        self._attributes = {
            "source_power_w": current_power,
            "last_updated": datetime.now().isoformat(),
            "plantId": getattr(self.hub, "senceId", ""),
        }

        if not hasattr(self, "hass") or self.hass is None:
            return

        self.async_write_ha_state()

    async def async_set_energy(self, value: float = 0.0) -> None:
        """Service handler: set the accumulated energy (kWh), e.g. reset or align with the inverter."""
        self._total_energy = max(0.0, float(value))
        self._state = round(self._total_energy, 3)
        self._last_time = time.monotonic()
        _LOGGER.info("Energy counter %s set to %s kWh", self._unique_id, self._total_energy)
        self.async_write_ha_state()


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up AECC Cloud sensor platform from config entry."""
    sensors = hass.data[DOMAIN]['device_manager'].entities.get("sensor", [])
    async_add_entities(sensors)

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_SET_ENERGY,
        {vol.Optional("value", default=0.0): vol.All(vol.Coerce(float), vol.Range(min=0))},
        _async_handle_set_energy,
    )
    _LOGGER.info(f"Loaded {len(sensors)} AECC Cloud sensors: {[s.name for s in sensors]}")
    return True
