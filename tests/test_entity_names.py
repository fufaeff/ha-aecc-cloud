"""All entities use has_entity_name and must not repeat the device name/SN in their own name."""
from __future__ import annotations

import asyncio
import sys

import pytest

SN = "80311608140057"
SOCKET_SN = "SOCKET001"


class FakeHub:
    """Minimal hub for DeviceEntityManager: records entities, serves one displayMap."""

    def __init__(self):
        self.senceId = "82979"
        self.plant_name = "Garazh"
        self.plants = []
        self.total_data = {}
        self.device_data = {}
        self.entities = []

    def add_entity(self, entity):
        self.entities.append(entity)

    async def fetch_device_info(self, device_type, device_sn):
        return {"displayMap": {"Output Priority": "GPB", "Mains voltage": "230.1V"}}

    def get_setting_item(self, *a, **k):
        return None

    def get_setting_choice(self, *a, **k):
        return None


@pytest.fixture
def entities(entry_module):
    """Every entity DeviceEntityManager builds for an inverter plus a smart socket."""
    sys.modules.pop("aecc_plugin.device_entity_manager", None)
    from aecc_plugin.device_entity_manager import DeviceEntityManager

    hub = FakeHub()
    manager = DeviceEntityManager(object(), hub)
    data = {
        "solarSn": SN,
        "solarType": 55,
        "loadList": [
            {"deviceSn": SOCKET_SN, "deviceName": "Boiler", "iconType": 5, "type": 1,
             "deviceCodeType": 0, "status": 1, "switchStatus": 0},
        ],
    }
    created = asyncio.run(manager.create_entities_from_data(data))
    return [e for platform in created.values() for e in platform]


def _name(entity) -> str:
    name = type(entity).__dict__.get("name")
    if isinstance(name, property):
        return name.fget(entity)
    return getattr(entity, "_attr_name", None)


def test_entities_created(entities):
    platforms = {type(e).__name__ for e in entities}
    assert {"AeccSensor", "AeccSwitch", "AeccWorkingModeSelect", "AeccSettingNumber"} <= platforms


def test_all_entities_use_has_entity_name(entities):
    missing = sorted({type(e).__name__ for e in entities if not getattr(e, "_attr_has_entity_name", False)})
    assert missing == []


def test_names_do_not_repeat_device(entities):
    offenders = [
        (type(e).__name__, _name(e))
        for e in entities
        if any(token in str(_name(e)) for token in (SN, SOCKET_SN, "Boiler"))
    ]
    assert offenders == []


def test_select_and_number_names(entities):
    names = {_name(e) for e in entities}
    assert {"Working Mode", "Charger Source Priority", "Active Plant",
            "Mains Charging Current", "SOC for Switching to Mains"} <= names


def test_switch_has_device_info(entities):
    switch = next(e for e in entities if type(e).__name__ == "AeccSwitch" and _name(e) == "switch")
    assert switch.device_info["identifiers"] == {("aecc_cloud_plugin", SOCKET_SN)}
    assert switch.device_info["name"] == "Boiler"
