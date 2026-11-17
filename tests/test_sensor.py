"""Sensor value parsing and load power calculation."""
from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("953w", (953, "W")),
        ("12.5kwh", (12.5, "kWh")),
        (42, (42, "")),
        ("230.5 V", (230.5, "V")),
        ("-120W", (-120, "W")),
        ("80311608140057", (80311608140057, "")),
        ("GPB", ("GPB", "")),
        ("Platova", ("Platova", "")),
        ("2026-02-26 20:56:55", ("2026-02-26 20:56:55", "")),
        ("V1.0.58", ("V1.0.58", "")),
    ],
)
def test_parse_reading(sensor_module, raw, expected):
    got = sensor_module.parse_reading(raw)
    assert got == expected
    assert type(got[0]) is type(expected[0])


def _fake_sensor(sensor_module, unit):
    class Fake:
        _apply_reading = sensor_module.AeccSensor._apply_reading

    fake = Fake()
    fake._unit = unit
    fake._state = None
    return fake


def test_unit_kept_when_reading_has_none(sensor_module):
    s = _fake_sensor(sensor_module, "W")
    s._apply_reading("953")
    assert (s._state, s._unit) == (953, "W")


def test_text_on_numeric_sensor_is_unknown(sensor_module):
    s = _fake_sensor(sensor_module, "W")
    s._apply_reading("--")
    assert s._state is None


def test_text_sensor_keeps_text_and_picks_up_unit(sensor_module):
    s = _fake_sensor(sensor_module, "")
    s._apply_reading("PNG")
    assert (s._state, s._unit) == ("PNG", "")
    s._apply_reading("231.4V")
    assert (s._state, s._unit) == (231.4, "V")


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        # homePower and loadPower are the same load and must not be summed
        ({"homePower": "654W", "loadPower": "654W", "chargerTotalPower": 0}, 654),
        ({"homePower": 0, "loadPower": "500W", "chargerTotalPower": "100W"}, 600),
        ({}, 0),
    ],
)
def test_total_load_power(sensor_module, data, expected):
    assert sensor_module.total_load_power(data) == expected
