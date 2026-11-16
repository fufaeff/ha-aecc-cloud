"""AECC Cloud Integration for Home Assistant."""

from __future__ import annotations

import logging
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import Platform
import homeassistant.helpers.config_validation as cv
from .hub import MyIntegrationHub
from .const import DOMAIN, BASE_URL  # pylint:disable=unused-import

PLATFORMS = [Platform.SENSOR, Platform.SWITCH, Platform.SELECT, Platform.NUMBER]
PLANT_SERVICES = ("service_switch_plant", "switch_plant")
MODE_SERVICES = ("set_working_mode", "service_set_working_mode")
CHARGER_SERVICES = ("set_charger_priority", "service_set_charger_priority")

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the AECC Cloud platform from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    hub = MyIntegrationHub(
        hass,
        entry.data["username"],
        entry.data["password"],
        entry.data["selected_device_id"],
    )
    hass.data[DOMAIN]['hub'] = hub
    hass.data[DOMAIN]['cur_plant_name'] = entry.data["selected_device_name"]

    # Initialize device entity manager
    from .device_entity_manager import DeviceEntityManager
    device_manager = DeviceEntityManager(hass, hub)
    hass.data[DOMAIN]['device_manager'] = device_manager

    # Authenticate and create initial entities
    await hub.login()

    device_data = await hub.getHomeCountData() or {}
    _LOGGER.debug(f"Device data received: {len(device_data)} fields")
    entities = await device_manager.create_entities_from_data(device_data)
    _LOGGER.debug(f"Created entities: {entities}")
    _LOGGER.debug(f"Created devices: {device_manager.devices}")

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    await hub.start_polling()
    await hub.start_schedule_login()

    # Register service to switch active plant
    async def async_switch_plant_service(call):
        """Service handler: switch active monitored plant."""
        plant_id = call.data.get("plant_id")
        if not plant_id:
            _LOGGER.warning("Switch plant service called without plant_id")
            return
        domain_data = hass.data.get(DOMAIN, {})
        current_hub = domain_data.get("hub")
        if not current_hub:
            _LOGGER.warning("Switch plant service called but hub is not initialized")
            return
        current_hub.senceId = str(plant_id)
        domain_data["cur_plant_name"] = str(plant_id)
        await current_hub.async_update_data()

    switch_plant_schema = vol.Schema(
        {
            vol.Required("plant_id"): cv.string,
        }
    )

    for s_name in PLANT_SERVICES:
        if not hass.services.has_service(DOMAIN, s_name):
            hass.services.async_register(
                DOMAIN,
                s_name,
                async_switch_plant_service,
                schema=switch_plant_schema,
            )

    # Register service to set inverter working mode
    async def async_set_working_mode_service(call):
        """Service handler: set inverter working mode (SBU, SUB, USB)."""
        mode = call.data.get("mode")
        device_sn = call.data.get("device_sn")
        if not mode:
            _LOGGER.warning("Set working mode called without mode parameter")
            return
        domain_data = hass.data.get(DOMAIN, {})
        current_hub = domain_data.get("hub")
        if not current_hub:
            _LOGGER.warning("Set working mode called but hub is not initialized")
            return
        await current_hub.set_working_mode(mode, device_sn=device_sn)
        await current_hub.async_update_data()

    set_working_mode_schema = vol.Schema(
        {
            vol.Required("mode"): cv.string,
            vol.Optional("device_sn"): cv.string,
        }
    )

    for s_name in MODE_SERVICES:
        if not hass.services.has_service(DOMAIN, s_name):
            hass.services.async_register(
                DOMAIN,
                s_name,
                async_set_working_mode_service,
                schema=set_working_mode_schema,
            )

    # Register service to set battery charger source priority
    async def async_set_charger_priority_service(call):
        """Service handler: set battery charger source priority (CSO, SNU, OSO, CUT)."""
        mode = call.data.get("mode")
        device_sn = call.data.get("device_sn")
        if not mode:
            _LOGGER.warning("Set charger priority called without mode parameter")
            return
        domain_data = hass.data.get(DOMAIN, {})
        current_hub = domain_data.get("hub")
        if not current_hub:
            _LOGGER.warning("Set charger priority called but hub is not initialized")
            return
        await current_hub.set_charger_priority(mode, device_sn=device_sn)
        await current_hub.async_update_data()

    set_charger_priority_schema = vol.Schema(
        {
            vol.Required("mode"): cv.string,
            vol.Optional("device_sn"): cv.string,
        }
    )

    for s_name in CHARGER_SERVICES:
        if not hass.services.has_service(DOMAIN, s_name):
            hass.services.async_register(
                DOMAIN,
                s_name,
                async_set_charger_priority_service,
                schema=set_charger_priority_schema,
            )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    hub = hass.data.get(DOMAIN, {}).get('hub')
    if hub:
        await hub.stop_polling()
        await hub.stop_schedule_login()

    for s_name in (*PLANT_SERVICES, *MODE_SERVICES, *CHARGER_SERVICES):
        if hass.services.has_service(DOMAIN, s_name):
            hass.services.async_remove(DOMAIN, s_name)

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data.pop(DOMAIN, None)
    return unload_ok
