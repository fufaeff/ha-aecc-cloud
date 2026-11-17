"""AECC Cloud Integration for Home Assistant."""

from __future__ import annotations

import logging
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.const import Platform
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
import homeassistant.helpers.config_validation as cv
from .hub import MyIntegrationHub, is_md5, md5_hash
from .const import DOMAIN

PLATFORMS = [Platform.SENSOR, Platform.SWITCH, Platform.SELECT, Platform.NUMBER]
PLANT_SERVICES = ("service_switch_plant", "switch_plant")
MODE_SERVICES = ("set_working_mode", "service_set_working_mode")
CHARGER_SERVICES = ("set_charger_priority", "service_set_charger_priority")

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the AECC Cloud platform from a config entry."""
    data = dict(entry.data)

    # Never keep the plain-text password: the cloud only needs its MD5 hash
    if not is_md5(data.get("password", "")):
        data["password"] = md5_hash(data["password"])
        hass.config_entries.async_update_entry(entry, data=data)
        _LOGGER.info("Stored password replaced with its hash")

    # Entries created before 1.2.1 have no unique_id: backfill it to block duplicates
    if entry.unique_id is None:
        hass.config_entries.async_update_entry(
            entry, unique_id=f"{data['username'].lower()}_{data['selected_device_id']}"
        )

    hub = MyIntegrationHub(hass, data["username"], data["password"], data["selected_device_id"])
    hub.plant_name = data.get("selected_device_name") or str(data["selected_device_id"])

    # Cloud unreachable or login rejected: let Home Assistant retry later
    if not await hub.login():
        raise ConfigEntryNotReady("Cannot log in to AEC Cloud")
    device_data = await hub.getHomeCountData()
    if not device_data:
        raise ConfigEntryNotReady("AEC Cloud returned no data for the plant")

    from .device_entity_manager import DeviceEntityManager

    device_manager = DeviceEntityManager(hass, hub)
    hub.device_manager = device_manager
    await device_manager.create_entities_from_data(device_data)
    _LOGGER.debug(f"Created devices: {device_manager.devices}")

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = hub
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    await hub.start_polling()
    await hub.start_schedule_login()

    _register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    hub = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if hub:
        await hub.stop_polling()
        await hub.stop_schedule_login()

    # Services are shared by all entries: remove them with the last one
    if not hass.data.get(DOMAIN):
        hass.data.pop(DOMAIN, None)
        for s_name in (*PLANT_SERVICES, *MODE_SERVICES, *CHARGER_SERVICES):
            if hass.services.has_service(DOMAIN, s_name):
                hass.services.async_remove(DOMAIN, s_name)
    return True


def _hubs(hass: HomeAssistant) -> list[MyIntegrationHub]:
    return list(hass.data.get(DOMAIN, {}).values())


def _hub_for_device(hass: HomeAssistant, device_sn: str | None) -> MyIntegrationHub:
    """Pick the entry that owns device_sn, or the only entry if no SN is given."""
    hubs = _hubs(hass)
    if not hubs:
        raise HomeAssistantError("AECC Cloud is not set up")
    if device_sn:
        for hub in hubs:
            if device_sn in hub.device_data or any(
                d.device_sn == device_sn for d in getattr(hub.device_manager, "devices", [])
            ):
                return hub
        raise HomeAssistantError(f"No AECC Cloud entry has device {device_sn}")
    if len(hubs) == 1:
        return hubs[0]
    raise HomeAssistantError("Several AECC Cloud entries are configured: specify device_sn")


def _hub_for_plant(hass: HomeAssistant, plant_id: str) -> MyIntegrationHub:
    """Pick the entry whose account has plant_id, or the only entry."""
    hubs = _hubs(hass)
    if not hubs:
        raise HomeAssistantError("AECC Cloud is not set up")
    for hub in hubs:
        if any(str(p.get("id")) == plant_id for p in hub.plants or [] if isinstance(p, dict)):
            return hub
    if len(hubs) == 1:
        return hubs[0]
    raise HomeAssistantError(f"No AECC Cloud entry has plant {plant_id}")


def _register_services(hass: HomeAssistant) -> None:
    """Register domain services once (shared by all config entries)."""

    async def async_switch_plant_service(call: ServiceCall) -> None:
        """Switch the monitored plant."""
        plant_id = str(call.data["plant_id"])
        hub = _hub_for_plant(hass, plant_id)
        hub.senceId = plant_id
        hub.plant_name = next(
            (
                p.get("plantName") or plant_id
                for p in hub.plants or []
                if isinstance(p, dict) and str(p.get("id")) == plant_id
            ),
            plant_id,
        )
        await hub.async_update_data()

    async def async_set_working_mode_service(call: ServiceCall) -> None:
        """Set inverter Output Priority."""
        hub = _hub_for_device(hass, call.data.get("device_sn"))
        await hub.set_working_mode(call.data["mode"], device_sn=call.data.get("device_sn"))
        await hub.async_update_data()

    async def async_set_charger_priority_service(call: ServiceCall) -> None:
        """Set inverter Charging Priority."""
        hub = _hub_for_device(hass, call.data.get("device_sn"))
        await hub.set_charger_priority(call.data["mode"], device_sn=call.data.get("device_sn"))
        await hub.async_update_data()

    plant_schema = vol.Schema({vol.Required("plant_id"): cv.string})
    mode_schema = vol.Schema(
        {
            vol.Required("mode"): cv.string,
            vol.Optional("device_sn"): cv.string,
        }
    )

    for names, handler, schema in (
        (PLANT_SERVICES, async_switch_plant_service, plant_schema),
        (MODE_SERVICES, async_set_working_mode_service, mode_schema),
        (CHARGER_SERVICES, async_set_charger_priority_service, mode_schema),
    ):
        for s_name in names:
            if not hass.services.has_service(DOMAIN, s_name):
                hass.services.async_register(DOMAIN, s_name, handler, schema=schema)
