import logging
from typing import Dict, List, Optional
from .device import (
    BaseDevice,
    DeviceType,
    EnergyManager,
    Meter,
    Socket,
    Charger,
    Inverter,
    Battery,
    Relay,
    PowerController,
    HeatPump,
)

_LOGGER = logging.getLogger(__name__)


class DeviceManager:
    """Device manager responsible for creating and maintaining device instances."""

    def __init__(self, hass, hub):
        self.hass = hass
        self.hub = hub
        self.devices: Dict[str, BaseDevice] = {}
        self._device_type_map = {
            DeviceType.ENERGY_MANAGER: EnergyManager,
            DeviceType.INVERTER: Inverter,
            DeviceType.BATTERY: Battery,
            DeviceType.SOCKET: Socket,
            DeviceType.CHARGER: Charger,
            DeviceType.METER: Meter,
            DeviceType.RELAY: Relay,
            DeviceType.POWER_CONTROLLER: PowerController,
            DeviceType.HEAT_PUMP: HeatPump,
        }

    def create_device(self, device_info: dict) -> Optional[BaseDevice]:
        """Create corresponding device instance based on device information."""
        device_type = device_info.get("iconType")
        if not device_type:
            _LOGGER.error(f"Missing iconType in device info: {device_info}")
            return None

        try:
            device_type_enum = DeviceType(device_type)
            device_class = self._device_type_map.get(device_type_enum)
            if not device_class:
                _LOGGER.error(f"Unknown device type: {device_type}")
                return None

            device = device_class(self.hass, self.hub)
            device.update_device_info(device_info)
            self.devices[device.device_sn] = device
            return device

        except ValueError as e:
            _LOGGER.error(f"Failed to create device instance: {e}")
            return None

    def get_device(self, device_sn: str) -> Optional[BaseDevice]:
        """Get device instance by serial number."""
        return self.devices.get(device_sn)

    def get_devices_by_type(self, device_type: DeviceType) -> List[BaseDevice]:
        """Get all device instances of a given type."""
        return [device for device in self.devices.values() if device.device_type == device_type]

    def update_device(self, device_sn: str, device_info: dict):
        """Update device information."""
        device = self.get_device(device_sn)
        if device:
            device.update_device_info(device_info)
        else:
            _LOGGER.warning(f"Device not found: {device_sn}")
