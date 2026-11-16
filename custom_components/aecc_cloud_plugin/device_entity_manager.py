import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from .sensor import AeccSensor, AeccCalculatedEnergySensor
from .switch import AeccSwitch
from .select import (
    AeccWorkingModeSelect,
    AeccPlantSelect,
    AeccChargerPrioritySelect,
    AeccSettingSelect,
    SETTING_SELECTS,
)
from .number import AeccSettingNumber, SETTING_NUMBERS
from .device_manager import DeviceManager

_LOGGER = logging.getLogger(__name__)


class DeviceEntityManager:
    """Device entity manager responsible for creating and maintaining device entities."""

    def __init__(self, hass: HomeAssistant, hub):
        self.hass = hass
        self.hub = hub
        self.dcm = DeviceManager(self.hass, self.hub)
        self.entities: dict[str, list[Entity]] = {"sensor": [], "switch": [], "select": [], "number": []}
        self.devices = []

    async def create_entities_from_data(self, data: dict) -> dict[str, list[Any]]:
        """Create device entities from cloud API response data."""
        entities: dict[str, list[Any]] = {"sensor": [], "switch": [], "select": [], "number": []}

        # Process load / smart plug device list
        if 'loadList' in data and data['loadList']:
            for load in data['loadList']:
                if load.get('iconType') == 5:  # Socket / Plug type
                    _LOGGER.debug(f"Creating socket entity: {load}")
                    device = self.dcm.create_device(device_info=load)
                    self.devices.append(device)
                    entity = AeccSwitch(self.hass, self.hub, device, "switch", device.device_sn + "_socket_switch")
                    entities[entity.pf].append(entity)

                    # Smart linkage (unimplemented, disabled)
                    intervention = AeccSwitch(self.hass, self.hub, device, "intervention", device.device_sn + "_socket_intervention")
                    intervention.disable_entity()
                    entities[entity.pf].append(intervention)

                    # AI electricity reservation (unimplemented, disabled)
                    ai_switch = AeccSwitch(self.hass, self.hub, device, "AI electricity reservation", device.device_sn + "_socket_ai")
                    ai_switch.disable_entity()
                    entities[entity.pf].append(ai_switch)

                    entities["sensor"].append(AeccSensor(self.hub, device, "device name", device.device_sn + "_device_name", ""))
                    entities["sensor"].append(AeccSensor(self.hub, device, "device sn", device.device_sn + "_socket_sn", ""))
                    entities["sensor"].append(AeccSensor(self.hub, device, "rate power", device.device_sn + "_socket_rate", "W"))
                    entities["sensor"].append(AeccSensor(self.hub, device, "current", device.device_sn + "_socket_cur", "A"))
                    entities["sensor"].append(AeccSensor(self.hub, device, "power", device.device_sn + "_socket_pow", "W"))
                    entities["sensor"].append(AeccSensor(self.hub, device, "vol", device.device_sn + "_socket_vol", "V"))
                    entities["sensor"].append(AeccSensor(self.hub, device, "today Energy", device.device_sn + "_socket_elec_day", "kWh"))
                    entities["sensor"].append(AeccSensor(self.hub, device, "total Energy", device.device_sn + "_socket_elec_total", "kWh"))

        # Process EV charger device list
        if 'chargerList' in data and data['chargerList']:
            for charger in data['chargerList']:
                if charger.get('iconType') == 6:  # EV Charger type
                    _LOGGER.debug(f"Creating charger entity: {charger}")
                    device = self.dcm.create_device(device_info=charger)
                    self.devices.append(device)
                    entity = AeccSwitch(self.hass, self.hub, device, "switch", device.device_sn + "_charger_switch")
                    entities[entity.pf].append(entity)

                    # Smart linkage (unimplemented, disabled)
                    intervention = AeccSwitch(self.hass, self.hub, device, "intervention", device.device_sn + "_charger_intervention")
                    intervention.disable_entity()
                    entities[entity.pf].append(intervention)

                    # AI electricity reservation (unimplemented, disabled)
                    ai_switch = AeccSwitch(self.hass, self.hub, device, "AI electricity reservation", device.device_sn + "_charger_ai")
                    ai_switch.disable_entity()
                    entities[entity.pf].append(ai_switch)

                    entities["sensor"].append(AeccSensor(self.hub, device, "device name", device.device_sn + "_device_name", ""))
                    entities["sensor"].append(AeccSensor(self.hub, device, "charger status", device.device_sn + "_charger_status", ""))
                    entities["sensor"].append(AeccSensor(self.hub, device, "vol", device.device_sn + "_charger_vol", "V"))
                    entities["sensor"].append(AeccSensor(self.hub, device, "current", device.device_sn + "_charger_cur", "A"))
                    entities["sensor"].append(AeccSensor(self.hub, device, "power", device.device_sn + "_charger_pow", "kW"))
                    entities["sensor"].append(AeccSensor(self.hub, device, "Temperature", device.device_sn + "_charger_temp", "℃"))
                    entities["sensor"].append(AeccSensor(self.hub, device, "charger sn", device.device_sn + "_charger_sn", ""))

        # Process heat pump / power controller list
        if 'heatPumpList' in data and data['heatPumpList']:
            for heat in data['heatPumpList']:
                if heat.get('iconType') == 9:  # Power controller
                    _LOGGER.debug(f"Creating power controller entity: {heat}")
                    device = self.dcm.create_device(device_info=heat)
                    self.devices.append(device)
                    entity = AeccSwitch(self.hass, self.hub, device, "switch", device.device_sn + "_heat_pump_switch")
                    entities[entity.pf].append(entity)

        # Process smart meter if present
        if data.get("emSn") is not None:
            res = await self.hub.fetch_device_info(data.get("emType"), data.get("emSn"))
            if res:
                _LOGGER.debug(f"Creating smart meter device: {res}")
                em = self.dcm.create_device(device_info={
                    "deviceSn": data.get("emSn"),
                    "deviceName": data.get("emSn"),
                    "datalogSn": data.get("emSn"),
                    "iconType": 7,
                    "type": data.get("emType"),
                    "deviceCodeType": 0,
                    "status": 0,
                    "switchStatus": 0,
                })
                self.devices.append(em)
                display_map = res.get("displayMap", {})
                for k, v in display_map.items():
                    entities["sensor"].append(AeccSensor(self.hub, em, k, em.device_sn + k, ""))

        # Process battery / energy storage if present
        if data.get("solarSn") is not None:
            res = await self.hub.fetch_device_info(data.get("solarType"), data.get("solarSn"))
            if res:
                _LOGGER.debug(f"Creating storage device: {res}")
                bs = self.dcm.create_device(device_info={
                    "deviceSn": data.get("solarSn"),
                    "deviceName": data.get("solarSn"),
                    "datalogSn": data.get("solarSn"),
                    "iconType": 3,
                    "type": data.get("solarType"),
                    "deviceCodeType": 0,
                    "status": 0,
                    "switchStatus": 0,
                })
                self.devices.append(bs)
                display_map = res.get("displayMap", {})
                for k, v in display_map.items():
                    entities["sensor"].append(AeccSensor(self.hub, bs, k, bs.device_sn + k, ""))

        # Process master energy management device
        master_sn = (
            data.get("deviceSn")
            or data.get("systemSn")
            or data.get("solarSn")
            or data.get("emSn")
            or (str(self.hub.senceId) if getattr(self.hub, 'senceId', None) else None)
            or "master"
        )
        master = self.dcm.create_device(device_info={
            "deviceSn": master_sn,
            "deviceName": data.get("deviceName") or master_sn,
            "datalogSn": data.get("datalogSn") or master_sn,
            "iconType": 3,
            "type": data.get("deviceType") or data.get("solarType") or 0,
            "deviceCodeType": 0,
            "status": 0,
            "switchStatus": 0,
        })
        if master:
            self.devices.append(master)
            _LOGGER.info(f"Master energy device registered: {master.device_sn}")

            entities["sensor"].append(AeccSensor(self.hub, master, "plant_name", "plant_name", ""))
            entities["sensor"].append(AeccSensor(self.hub, master, "emStatus", "emStatus", ""))
            entities["sensor"].append(AeccSensor(self.hub, master, "emType", "emType", ""))
            entities["sensor"].append(AeccSensor(self.hub, master, "emSN", "emSn", ""))

            # Power telemetry sensors
            entities["sensor"].append(AeccSensor(self.hub, master, "Total Load Power", "totalLoadPower", "W"))
            entities["sensor"].append(AeccSensor(self.hub, master, "Solar Power", "solarPower", "W"))
            entities["sensor"].append(AeccCalculatedEnergySensor(self.hub, master, "Total Load Energy", "total_load_energy_calc", "total_load"))
            entities["sensor"].append(AeccCalculatedEnergySensor(self.hub, master, "Solar Energy", "solar_energy_calc", "solar"))
            entities["sensor"].append(AeccSensor(self.hub, master, "Grid Power", "gridPower", "W"))
            entities["sensor"].append(AeccSensor(self.hub, master, "Mains Power", "mainsPower", "W"))
            entities["sensor"].append(AeccSensor(self.hub, master, "Load Power", "loadPower", "W"))
            entities["sensor"].append(AeccSensor(self.hub, master, "Home Power", "homePower", "W"))
            entities["sensor"].append(AeccSensor(self.hub, master, "Battery Power", "batPower", "W"))
            entities["sensor"].append(AeccCalculatedEnergySensor(self.hub, master, "Battery Charge Energy", "battery_charge_energy_calc", "battery_charge"))
            entities["sensor"].append(AeccCalculatedEnergySensor(self.hub, master, "Battery Discharge Energy", "battery_discharge_energy_calc", "battery_discharge"))
            entities["sensor"].append(AeccSensor(self.hub, master, "Charger Total Power", "chargerTotalPower", "W"))
            entities["sensor"].append(AeccSensor(self.hub, master, "AC Power", "acPower", "W"))
            entities["sensor"].append(AeccSensor(self.hub, master, "Off-Grid AC Power", "offGridAcPower", "W"))
            entities["sensor"].append(AeccSensor(self.hub, master, "DC Power", "dcPower", "W"))

            # Energy statistics sensors
            entities["sensor"].append(AeccSensor(self.hub, master, "Battery SOC", "batSoc", "%"))
            entities["sensor"].append(AeccSensor(self.hub, master, "Solar Daily Energy", "solarDayElec", "kWh"))
            entities["sensor"].append(AeccSensor(self.hub, master, "Grid Daily Energy", "gridDayElec", "kWh"))
            entities["sensor"].append(AeccSensor(self.hub, master, "Load Daily Energy", "loadDayElec", "kWh"))
            entities["sensor"].append(AeccSensor(self.hub, master, "Battery Daily Discharge Energy", "batteryDayDischargeElec", "kWh"))
            entities["sensor"].append(AeccSensor(self.hub, master, "Daily Revenue", "dayRevenue", "$"))
            entities["sensor"].append(AeccSensor(self.hub, master, "Total Energy", "totalEnergy", "kWh"))
            entities["sensor"].append(AeccSensor(self.hub, master, "Today Energy", "todayEnergy", "kWh"))
            entities["sensor"].append(AeccSensor(self.hub, master, "Month Energy", "monthEnergy", "kWh"))
            entities["sensor"].append(AeccSensor(self.hub, master, "Year Energy", "yearEnergy", "kWh"))

            # Status sensors
            entities["sensor"].append(AeccSensor(self.hub, master, "Device Online Status", "onlineStatus", ""))
            entities["sensor"].append(AeccSensor(self.hub, master, "Device Type", "deviceType", ""))
            entities["sensor"].append(AeccSensor(self.hub, master, "Solar Work Mode", "solarWorkMode", ""))
            entities["sensor"].append(AeccSensor(self.hub, master, "Grid Work Mode", "gridWorkMode", ""))
            entities["sensor"].append(AeccSensor(self.hub, master, "Mains Work Mode", "mainsWorkMode", ""))
            entities["sensor"].append(AeccSensor(self.hub, master, "Load Work Mode", "loadWorkMode", ""))
            entities["sensor"].append(AeccSensor(self.hub, master, "Home Work Mode", "homeWorkMode", ""))
            entities["sensor"].append(AeccSensor(self.hub, master, "After Load Work Mode", "afterLoadWorkMode", ""))
            entities["sensor"].append(AeccSensor(self.hub, master, "Before Load Work Mode", "beforeLoadWorkMode", ""))
            entities["sensor"].append(AeccSensor(self.hub, master, "Off-Grid Load Work Mode", "offGridLoadWorkMode", ""))
            entities["sensor"].append(AeccSensor(self.hub, master, "Battery Work Mode", "batWorkMode", ""))
            entities["sensor"].append(AeccSensor(self.hub, master, "AC Work Mode", "acWorkMode", ""))
            entities["sensor"].append(AeccSensor(self.hub, master, "Off-Grid AC Switch", "offGridAcSwitch", ""))
            entities["sensor"].append(AeccSensor(self.hub, master, "On-Grid Power Work Mode", "onGridPowerWorkMode", ""))
            entities["sensor"].append(AeccSensor(self.hub, master, "Battery Status", "batStatus", ""))
            entities["sensor"].append(AeccSensor(self.hub, master, "On-Grid Status", "onGridStatus", ""))
            entities["sensor"].append(AeccSensor(self.hub, master, "Show Electricity Plan", "whetherShowElcPlan", ""))
            entities["sensor"].append(AeccSensor(self.hub, master, "Device Name", "deviceName", ""))

            # Detailed power flow sensors
            entities["sensor"].append(AeccSensor(self.hub, master, "socketPower", "socketPower", "W"))
            entities["sensor"].append(AeccSensor(self.hub, master, "inverterPower", "inverterPower", "W"))
            entities["sensor"].append(AeccSensor(self.hub, master, "yxWith2InvPower", "yxWith2InvPower", "W"))
            entities["sensor"].append(AeccSensor(self.hub, master, "onGridActivePower", "onGridActivePower", "W"))
            entities["sensor"].append(AeccSensor(self.hub, master, "afterLoadPower", "afterLoadPower", "W"))
            entities["sensor"].append(AeccSensor(self.hub, master, "beforeLoadPower", "beforeLoadPower", "W"))
            entities["sensor"].append(AeccSensor(self.hub, master, "offGridLoadPower", "offGridLoadPower", "W"))

            # Metadata sensors
            entities["sensor"].append(AeccSensor(self.hub, master, "Device SN", "deviceSn", ""))
            entities["sensor"].append(AeccSensor(self.hub, master, "Battery SN", "batSn", ""))
            entities["sensor"].append(AeccSensor(self.hub, master, "System SN", "systemSn", ""))
            entities["sensor"].append(AeccSensor(self.hub, master, "Solar Type", "solarType", ""))
            entities["sensor"].append(AeccSensor(self.hub, master, "Grid Type", "gridType", ""))
            entities["sensor"].append(AeccSensor(self.hub, master, "Mains Type", "mainsType", ""))
            entities["sensor"].append(AeccSensor(self.hub, master, "Load Type", "loadType", ""))
            entities["sensor"].append(AeccSensor(self.hub, master, "Battery Type", "batType", ""))
            entities["sensor"].append(AeccSensor(self.hub, master, "AI System Status", "aiSystemStatus", ""))

            # Select entities
            entities["select"].append(AeccWorkingModeSelect(self.hass, self.hub, master))
            entities["select"].append(AeccPlantSelect(self.hass, self.hub, master))
            entities["select"].append(AeccChargerPrioritySelect(self.hass, self.hub, master))

            # Extra inverter settings (available once getSettingInfo has been loaded)
            for field, name, icon in SETTING_SELECTS:
                entities["select"].append(AeccSettingSelect(self.hub, master, field, name, icon))
            for field, name, unit, vmin, vmax, icon in SETTING_NUMBERS:
                entities["number"].append(
                    AeccSettingNumber(self.hub, master, field, name, unit, vmin, vmax, icon)
                )

        self.entities = entities
        return entities
