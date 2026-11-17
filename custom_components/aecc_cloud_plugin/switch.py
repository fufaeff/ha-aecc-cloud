import logging
from datetime import datetime
import re

from homeassistant.components.switch import SwitchEntity, SwitchDeviceClass
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class AeccSwitch(SwitchEntity):
    """AECC Cloud switch entity."""

    def __init__(self, hass, hub, device, name: str, key: str):
        """Initialize the switch."""
        super().__init__()
        self.device = device
        self.hass = hass
        self.hub = hub
        self._state = STATE_OFF
        self.pf = "switch"
        self._available = True
        self._attr_device_class = SwitchDeviceClass.OUTLET if getattr(device, "icon_type", None) == 5 else SwitchDeviceClass.SWITCH
        self._key = key
        self._name = name
        self._unique_id = self._generate_unique_id()
        self._unit = ""
        self._attributes = {}
        _LOGGER.debug(f"Created switch entity: {self._name}, sn={self.device.device_sn}")
        # Register switch to hub for updates
        hub.add_entity(self)

    def _generate_unique_id(self) -> str:
        device_sn = re.sub(r"[^a-z0-9]", "", self.device.device_sn.lower())
        key = re.sub(r"[^a-z0-9]", "", self._name.lower())
        return f"{device_sn}_{key}"

    @property
    def unique_id(self) -> str:
        return self._unique_id

    @property
    def name(self) -> str:
        return f"{self.device.device_sn} {self._name}"

    @property
    def available(self) -> bool:
        return self._available

    @property
    def is_on(self) -> bool:
        """Return true if switch is on."""
        return self._state == STATE_ON

    def disable_entity(self):
        """Disable the entity."""
        self._available = False

    def update_data(self, new_data: dict, d: dict, ai: dict):
        """Update switch state and attributes from polled data."""
        v = new_data.get(self._key)
        if 'loadList' in new_data and new_data['loadList']:
            for load in new_data['loadList']:
                if v is None:
                    sn = load.get('deviceSn')
                    if sn == self.device.device_sn:
                        v = load.get('switchStatus')
                        break

        if v is None:
            if 'chargerList' in new_data and new_data['chargerList']:
                for charger in new_data['chargerList']:
                    if v is None:
                        sn = charger.get('deviceSn')
                        if sn == self.device.device_sn:
                            v = charger.get('switchStatus')
                            break

        if v is None:
            if 'heatPumpList' in new_data and new_data['heatPumpList']:
                for heat in new_data['heatPumpList']:
                    if v is None:
                        sn = heat.get('deviceSn')
                        if sn == self.device.device_sn:
                            v = heat.get('switchStatus')
                            break

        if v is not None:
            self._state = STATE_ON if v == 1 else STATE_OFF
            _LOGGER.debug(f"{self._name} updated state: {self._state}")
        else:
            self._state = STATE_OFF

        if not hasattr(self, "hass") or self.hass is None:
            _LOGGER.debug("Entity not initialized yet, skipping state update")
            return

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

        self._attributes = {
            "last_updated": datetime.now().isoformat(),
            "attrs": attrs,
        }
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs):
        """Turn the switch on."""
        _LOGGER.info(f"Turning on switch: {self._name} (iconType={self.device.icon_type})")
        if self.device.icon_type == 5:
            await self.hub.switch_socket(self.device.device_sn, 1)
        elif self.device.icon_type == 6:
            await self.hub.switch_charger(self.device.device_sn, 1)
        else:
            await self.hub.switch_product(self.device.device_sn, 1)
        self._state = STATE_ON
        self.async_write_ha_state()
        await self.hub.async_update_data()

    async def async_turn_off(self, **kwargs):
        """Turn the switch off."""
        _LOGGER.info(f"Turning off switch: {self._name} (iconType={self.device.icon_type})")
        if self.device.icon_type == 5:
            await self.hub.switch_socket(self.device.device_sn, 0)
        elif self.device.icon_type == 6:
            await self.hub.switch_charger(self.device.device_sn, 0)
        else:
            await self.hub.switch_product(self.device.device_sn, 0)
        self._state = STATE_OFF
        self.async_write_ha_state()
        await self.hub.async_update_data()


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up AECC Cloud switch platform from config entry."""
    switches = hass.data[DOMAIN][config_entry.entry_id].device_manager.entities.get("switch", [])
    async_add_entities(switches)
    _LOGGER.info(f"Loaded {len(switches)} AECC Cloud switches")
