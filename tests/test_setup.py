"""Config entry setup/unload: retry on cloud failure, password hashing, several entries."""
from __future__ import annotations

import asyncio
import hashlib
import sys
import types

import pytest

from conftest import ConfigEntryNotReady, HomeAssistantError

DOMAIN = "aecc_cloud_plugin"
PASSWORD = "secret-password"
PASSWORD_MD5 = hashlib.md5(PASSWORD.encode()).hexdigest()


class FakeServices:
    def __init__(self):
        self.registered = {}

    def has_service(self, domain, name):
        return (domain, name) in self.registered

    def async_register(self, domain, name, handler, schema=None):
        self.registered[(domain, name)] = handler

    def async_remove(self, domain, name):
        self.registered.pop((domain, name), None)


class FakeConfigEntries:
    def __init__(self):
        self.updated = []

    def async_update_entry(self, entry, data=None, unique_id=None):
        if data is not None:
            entry.data = data
            self.updated.append(data)
        if unique_id is not None:
            entry.unique_id = unique_id

    async def async_forward_entry_setups(self, entry, platforms):
        return True

    async def async_unload_platforms(self, entry, platforms):
        return True


class FakeHass:
    def __init__(self):
        self.data = {}
        self.services = FakeServices()
        self.config_entries = FakeConfigEntries()


class FakeEntry:
    def __init__(self, entry_id, plant_id="82979", password=PASSWORD, unique_id=None):
        self.entry_id = entry_id
        self.unique_id = unique_id
        self.data = {
            "username": "user@example.com",
            "password": password,
            "selected_device_id": plant_id,
            "selected_device_name": f"Plant {plant_id}",
        }


class FakeDeviceManager:
    def __init__(self, hass, hub):
        self.devices = []
        self.entities = {"sensor": [], "switch": [], "select": [], "number": []}

    async def create_entities_from_data(self, data):
        sn = data.get("solarSn")
        if sn:
            self.devices.append(types.SimpleNamespace(device_sn=sn, type=55))
        return self.entities


@pytest.fixture
def setup(entry_module, hub_module, monkeypatch):
    """Patch network calls; returns a function to control login/data results."""
    state = {"login": True, "data": {"solarSn": "SN1"}}

    async def fake_login(self, now=None):
        return state["login"]

    async def fake_home(self):
        return state["data"]

    async def noop(self, *a, **k):
        return None

    hub_cls = hub_module.MyIntegrationHub
    monkeypatch.setattr(hub_cls, "login", fake_login)
    monkeypatch.setattr(hub_cls, "getHomeCountData", fake_home)
    for name in ("start_polling", "start_schedule_login", "stop_polling", "stop_schedule_login"):
        monkeypatch.setattr(hub_cls, name, noop)
    monkeypatch.setitem(
        sys.modules,
        "aecc_plugin.device_entity_manager",
        types.SimpleNamespace(DeviceEntityManager=FakeDeviceManager),
    )
    return state


def run(coro):
    return asyncio.run(coro)


def test_login_failure_raises_not_ready(entry_module, setup):
    setup["login"] = False
    hass = FakeHass()
    with pytest.raises(ConfigEntryNotReady):
        run(entry_module.async_setup_entry(hass, FakeEntry("e1")))
    assert not hass.data.get(DOMAIN)
    assert not hass.services.registered


def test_empty_cloud_data_raises_not_ready(entry_module, setup):
    setup["data"] = {}
    with pytest.raises(ConfigEntryNotReady):
        run(entry_module.async_setup_entry(FakeHass(), FakeEntry("e1")))


def test_plain_password_is_replaced_by_hash(entry_module, setup):
    hass, entry = FakeHass(), FakeEntry("e1")
    assert run(entry_module.async_setup_entry(hass, entry))
    assert entry.data["password"] == PASSWORD_MD5
    assert PASSWORD not in str(entry.data)


def test_hashed_password_left_as_is(entry_module, setup):
    hass, entry = FakeHass(), FakeEntry("e1", password=PASSWORD_MD5)
    assert run(entry_module.async_setup_entry(hass, entry))
    assert hass.config_entries.updated == []


def test_unique_id_backfilled_for_old_entries(entry_module, setup):
    entry = FakeEntry("e1", plant_id="82979")
    run(entry_module.async_setup_entry(FakeHass(), entry))
    assert entry.unique_id == "user@example.com_82979"


def test_existing_unique_id_kept(entry_module, setup):
    entry = FakeEntry("e1", unique_id="custom")
    run(entry_module.async_setup_entry(FakeHass(), entry))
    assert entry.unique_id == "custom"


def test_each_entry_gets_its_own_hub(entry_module, setup):
    hass = FakeHass()
    run(entry_module.async_setup_entry(hass, FakeEntry("e1", plant_id="1")))
    setup["data"] = {"solarSn": "SN2"}
    run(entry_module.async_setup_entry(hass, FakeEntry("e2", plant_id="2")))

    hubs = hass.data[DOMAIN]
    assert set(hubs) == {"e1", "e2"}
    assert hubs["e1"] is not hubs["e2"]
    assert hubs["e1"].plant_name == "Plant 1" and hubs["e2"].plant_name == "Plant 2"

    assert entry_module._hub_for_device(hass, "SN2") is hubs["e2"]
    with pytest.raises(HomeAssistantError):
        entry_module._hub_for_device(hass, None)  # ambiguous with two entries
    with pytest.raises(HomeAssistantError):
        entry_module._hub_for_device(hass, "UNKNOWN")


def test_single_entry_used_without_device_sn(entry_module, setup):
    hass = FakeHass()
    run(entry_module.async_setup_entry(hass, FakeEntry("e1")))
    assert entry_module._hub_for_device(hass, None) is hass.data[DOMAIN]["e1"]


def test_services_removed_with_last_entry(entry_module, setup):
    hass = FakeHass()
    e1, e2 = FakeEntry("e1", plant_id="1"), FakeEntry("e2", plant_id="2")
    run(entry_module.async_setup_entry(hass, e1))
    run(entry_module.async_setup_entry(hass, e2))
    assert hass.services.has_service(DOMAIN, "set_working_mode")

    assert run(entry_module.async_unload_entry(hass, e1))
    assert hass.services.has_service(DOMAIN, "set_working_mode")
    assert set(hass.data[DOMAIN]) == {"e2"}

    assert run(entry_module.async_unload_entry(hass, e2))
    assert not hass.services.registered
    assert DOMAIN not in hass.data


def test_is_md5(hub_module):
    assert hub_module.is_md5(PASSWORD_MD5)
    assert not hub_module.is_md5(PASSWORD)
    assert hub_module.md5_hash(PASSWORD) == PASSWORD_MD5
    assert hub_module.md5_hash(PASSWORD_MD5) == PASSWORD_MD5
