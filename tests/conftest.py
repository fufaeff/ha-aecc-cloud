"""Lightweight test harness: stub the few Home Assistant / aiohttp modules the plugin imports.

The tests exercise pure logic (payload building, value parsing, caching) and must run
without a Home Assistant installation, so the integration modules are loaded from a
synthetic package that does not execute the integration's __init__.py.
"""
from __future__ import annotations

import enum
import sys
import types
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "aecc_cloud_plugin"


class HomeAssistantError(Exception):
    """Stand-in for homeassistant.exceptions.HomeAssistantError."""


class ConfigEntryNotReady(HomeAssistantError):
    """Stand-in for homeassistant.exceptions.ConfigEntryNotReady."""


class Platform(str, enum.Enum):
    SENSOR = "sensor"
    SWITCH = "switch"
    SELECT = "select"
    NUMBER = "number"


def _voluptuous_stub() -> None:
    _module(
        "voluptuous",
        Schema=lambda schema, *a, **k: schema,
        Required=lambda key, **k: key,
        Optional=lambda key, **k: key,
        All=lambda *validators: validators,
        Coerce=lambda t: t,
        Range=lambda **k: None,
    )


class _Dummy:
    def __init__(self, *args, **kwargs):
        pass


class _Enum(enum.Enum):
    POWER = "power"
    ENERGY = "energy"
    BATTERY = "battery"
    MEASUREMENT = "measurement"
    TOTAL = "total"
    TOTAL_INCREASING = "total_increasing"
    KILO_WATT_HOUR = "kWh"
    WATT = "W"


def _module(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    mod.__dict__.update(attrs)
    sys.modules[name] = mod
    return mod


def _install_stubs() -> None:
    _module("homeassistant")
    _module(
        "homeassistant.exceptions",
        HomeAssistantError=HomeAssistantError,
        ConfigEntryNotReady=ConfigEntryNotReady,
    )
    _module("homeassistant.config_entries", ConfigEntry=object)
    _module("homeassistant.core", HomeAssistant=object, ServiceCall=object)
    _module("homeassistant.helpers")
    _module("homeassistant.helpers.config_validation", string=str)
    _module("homeassistant.helpers.aiohttp_client", async_get_clientsession=lambda hass: None)
    _module("homeassistant.helpers.event", async_track_time_interval=lambda *a, **k: None)
    _module("homeassistant.helpers.entity_platform")
    _module("homeassistant.helpers.restore_state", RestoreEntity=_Dummy)
    _module("homeassistant.components")
    _module(
        "homeassistant.components.sensor",
        SensorEntity=_Dummy,
        SensorDeviceClass=_Enum,
        SensorStateClass=_Enum,
    )
    _module("homeassistant.const", UnitOfEnergy=_Enum, UnitOfPower=_Enum, Platform=Platform)
    try:
        import voluptuous  # noqa: F401
    except ImportError:
        _voluptuous_stub()
    try:
        import aiohttp  # noqa: F401
    except ImportError:
        _module("aiohttp", ClientTimeout=object, ClientError=Exception, ContentTypeError=Exception)

    pkg = types.ModuleType("aecc_plugin")
    pkg.__path__ = [str(PLUGIN_DIR)]
    sys.modules["aecc_plugin"] = pkg


_install_stubs()


@pytest.fixture
def hub_module():
    from aecc_plugin import hub

    return hub


@pytest.fixture
def sensor_module():
    from aecc_plugin import sensor

    return sensor


@pytest.fixture
def entry_module():
    """The integration's __init__.py, loaded as aecc_plugin.entry (relative imports work)."""
    import importlib.util

    name = "aecc_plugin.entry"
    if name not in sys.modules:
        # Not a package: relative imports must resolve to aecc_plugin.<module>
        spec = importlib.util.spec_from_file_location(
            name, PLUGIN_DIR / "__init__.py", submodule_search_locations=None
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]
