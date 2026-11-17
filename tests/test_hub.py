"""Inverter settings: requests must match what the official AECC app sends."""
from __future__ import annotations

import asyncio
import json

import pytest

from conftest import HomeAssistantError

SN = "80311608140057"
DATALOG = "W5C6354413"

SETTINGS = {
    "result": 0,
    "msg": "Request successfully.",
    "obj": [
        {
            "masterId": 91,
            "settingSmallData": [
                {
                    "slaveId": 5338, "masterId": 91, "cellName": "Output Priority", "cellVal": 1,
                    "fieldName": "outputPriority2", "sendType": 0, "dtc": 60594,
                    "componentObj": {"choiceParamArr": [
                        {"val": "0", "name": "GPB"}, {"val": "1", "name": "PGB"},
                        {"val": "2", "name": "PBG"}, {"val": "3", "name": "MKS"},
                    ]},
                },
                {
                    "slaveId": 5340, "masterId": 91, "cellName": "Charging Priority", "cellVal": 0,
                    "fieldName": "chargePriority2", "sendType": 0,
                    "componentObj": {"choiceParamArr": [
                        {"val": "0", "name": "PNG"}, {"val": "1", "name": "OPV"}, {"val": "2", "name": "PVF"},
                    ]},
                },
                {
                    "slaveId": 5428, "masterId": 91, "cellName": "Mains Supply Charging Current", "cellVal": 60,
                    "fieldName": "mainsChargeCurrent", "sendType": 0,
                    "componentObj": {"choiceParamArr": [{"val": "10", "name": "10A"}, {"val": "60", "name": "60A"}]},
                },
                {
                    "slaveId": 5365, "masterId": 91, "cellName": "Set Low SOC Shutdown SOC", "cellVal": 10,
                    "fieldName": "lowSocShutdownSoc", "sendType": 0,
                    "componentObj": {
                        "inputCustomTipTxt": "5% ~ 50%",
                        "inputRegexp": {"regexpTxt": "^([5-9]|[1-4]\\d|50|65521)$"},
                    },
                },
            ],
        }
    ],
}

# Captured from the AECC iOS app when switching Output Priority to PGB
APP_SET_OUTPUT_PRIORITY = {
    "deviceSn": SN, "datalogSn": DATALOG, "deviceType": 55,
    "masterId": 91, "slaveId": 5338, "dtc": 60594, "sendType": 0,
    "object": {"outputPriority2": "1"},
}
APP_GET_SETTING_PARAMS = {"dtc": "60594", "displayType": "2", "deviceSn": SN, "datalogSn": DATALOG}


@pytest.fixture
def hub(hub_module, monkeypatch):
    calls: list[tuple] = []

    async def fake_get(self, headers, url, data=None, params=None, **kwargs):
        calls.append(("GET", url, headers, params))
        return SETTINGS

    async def fake_post(self, headers, url, data=None, params=None, **kwargs):
        calls.append(("POST", url, headers, json.loads(data)))
        return {"result": 0, "msg": "Setting successful.", "obj": {}}

    monkeypatch.setattr(hub_module.MyIntegrationHub, "get", fake_get)
    monkeypatch.setattr(hub_module.MyIntegrationHub, "post", fake_post)

    hub = hub_module.MyIntegrationHub(object(), "user", "password", "82979")
    hub.device_data[SN] = {"datalogSn": DATALOG, "deviceType": 55, "dtc": 60594}
    hub.calls = calls
    return hub


def run(coro):
    return asyncio.run(coro)


def test_output_priority_matches_app_request(hub):
    assert run(hub.set_working_mode("SUB (Solar -> Utility -> Battery)"))

    method, url, headers, body = hub.calls[-1]
    assert method == "POST"
    assert url == "https://api.ai-ec.cloud:8443/deviceSetConfig/setCustomParams"
    assert body == APP_SET_OUTPUT_PRIORITY
    assert headers["InterfaceType"] == "2" and headers["projectType"] == "1"


def test_get_setting_info_matches_app_request(hub):
    run(hub.fetch_setting_info())
    method, url, _, params = hub.calls[0]
    assert method == "GET"
    assert url.endswith("/deviceSetConfig/getSettingInfo")
    assert params == APP_GET_SETTING_PARAMS


def test_settings_are_cached(hub):
    run(hub.set_working_mode("PGB"))
    run(hub.set_charger_priority("PVF"))
    assert sum(1 for c in hub.calls if c[0] == "GET") == 1


def test_cached_value_updated_after_write(hub):
    run(hub.set_working_mode("GPB"))
    assert hub.get_setting_choice("outputPriority2") == "GPB"


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("CSO (Solar first / Приоритет солнце)", {"chargePriority2": "2"}),
        ("SNU (Solar and Utility / Солнце и сеть)", {"chargePriority2": "0"}),
        ("OSO (Only Solar / Только солнце)", {"chargePriority2": "1"}),
        ("PVF", {"chargePriority2": "2"}),
    ],
)
def test_charging_priority(hub, mode, expected):
    assert run(hub.set_charger_priority(mode))
    body = hub.calls[-1][3]
    assert body["slaveId"] == 5340
    assert body["object"] == expected


@pytest.mark.parametrize("mode", ["CUT (Utility first)", "XYZ"])
def test_unsupported_charging_priority_rejected(hub, mode):
    with pytest.raises(HomeAssistantError):
        run(hub.set_charger_priority(mode))
    assert not any(c[0] == "POST" for c in hub.calls)


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("USB (Utility -> Solar -> Battery)", "GPB"),
        ("SUB (Solar -> Utility -> Battery)", "PGB"),
        ("SBU (Solar -> Battery -> Utility)", "PBG"),
        ("MKS (Generator first)", "MKS"),
        ("pgb", "PGB"),
        ("nonsense", None),
    ],
)
def test_output_priority_code(hub_module, text, code):
    assert hub_module.output_priority_code(text) == code


def test_choice_setting(hub):
    assert run(hub.set_custom_param("mainsChargeCurrent", "10A"))
    body = hub.calls[-1][3]
    assert body["slaveId"] == 5428
    assert body["object"] == {"mainsChargeCurrent": "10"}
    assert hub.get_setting_choice("mainsChargeCurrent") == "10A"


def test_invalid_choice_rejected(hub):
    with pytest.raises(HomeAssistantError):
        run(hub.set_custom_param("mainsChargeCurrent", "999A"))


def test_numeric_setting_validated_by_server_regexp(hub):
    assert run(hub.set_custom_value("lowSocShutdownSoc", "20"))
    assert hub.calls[-1][3]["object"] == {"lowSocShutdownSoc": "20"}
    assert hub.get_setting_item("lowSocShutdownSoc")["cellVal"] == "20"

    with pytest.raises(HomeAssistantError):
        run(hub.set_custom_value("lowSocShutdownSoc", "70"))


def test_unknown_setting_rejected(hub):
    with pytest.raises(HomeAssistantError):
        run(hub.set_custom_param("doesNotExist", "On"))


def test_ai_system_cached(hub):
    run(hub.get_ai_system_cached())
    run(hub.get_ai_system_cached())
    assert sum(1 for c in hub.calls if "getAiSystem" in c[1]) == 1


def test_headers_redacted_in_logs(hub_module):
    redacted = hub_module._redact_headers({"token": "secret", "Token": "secret", "Cookie": "x", "Accept": "*/*"})
    assert redacted == {"token": "***", "Token": "***", "Cookie": "***", "Accept": "*/*"}
