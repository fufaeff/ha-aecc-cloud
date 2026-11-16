import logging
from enum import Enum
from .entity import BaseEntity

_LOGGER = logging.getLogger(__name__)


class DeviceType(Enum):
    ENERGY_MANAGER = 1  # Energy storage controller / manager
    INVERTER = 2  # Inverter
    BATTERY = 3  # Battery
    SOCKET = 5  # Smart socket / plug
    CHARGER = 6  # EV Charger
    METER = 7  # Smart meter
    RELAY = 8  # Relay
    POWER_CONTROLLER = 9  # Power controller
    HEAT_PUMP = 10  # Heat pump


class BaseDevice(BaseEntity):
    """Base device class, all specific device types inherit from this class."""

    def __init__(self, hass, hub, device_type: DeviceType):
        super().__init__(hass, hub)
        self.device_type = device_type
        self.device_name = None
        self.device_sn = None
        self.datalog_sn = None
        self.type = None
        self.icon_type = None
        self.device_mode = None
        self.device_code_type = None
        self.master_type = None
        self.rated_power = None
        self.power = None
        self.status = None
        self.switch_status = None
        self.inter_connect_status = None
        self.value = None

    def update_device_info(self, device_info: dict):
        """Update basic device information."""
        _LOGGER.debug(f"Updating device info: {device_info}")
        self.device_name = device_info.get("deviceName")
        self.device_sn = device_info.get("deviceSn")
        self.datalog_sn = device_info.get("datalogSn")
        self.type = device_info.get("type") if device_info.get("type") else -1
        self.icon_type = device_info.get("iconType")
        self.device_code_type = device_info.get("deviceCodeType")
        self.switch_status = device_info.get("switchStatus")
        self.status = device_info.get("status")


class EnergyManager(BaseDevice):
    """Energy manager device."""
    def __init__(self, hass, hub):
        super().__init__(hass, hub, DeviceType.ENERGY_MANAGER)


class Meter(BaseDevice):
    """Smart meter device."""
    def __init__(self, hass, hub):
        super().__init__(hass, hub, DeviceType.METER)


class Battery(BaseDevice):
    """Battery device."""
    def __init__(self, hass, hub):
        super().__init__(hass, hub, DeviceType.BATTERY)


class Socket(BaseDevice):
    """Socket / smart plug device."""
    def __init__(self, hass, hub):
        super().__init__(hass, hub, DeviceType.SOCKET)


class Charger(BaseDevice):
    """EV charger device."""
    def __init__(self, hass, hub):
        super().__init__(hass, hub, DeviceType.CHARGER)


class Inverter(BaseDevice):
    """Inverter device."""
    def __init__(self, hass, hub):
        super().__init__(hass, hub, DeviceType.INVERTER)


class Relay(BaseDevice):
    """Relay device."""
    def __init__(self, hass, hub):
        super().__init__(hass, hub, DeviceType.RELAY)


class PowerController(BaseDevice):
    """Power controller device."""
    def __init__(self, hass, hub):
        super().__init__(hass, hub, DeviceType.POWER_CONTROLLER)


class HeatPump(BaseDevice):
    """Heat pump device."""
    def __init__(self, hass, hub):
        super().__init__(hass, hub, DeviceType.HEAT_PUMP)
