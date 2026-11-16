# AECC Cloud for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories)
[![Validate](https://github.com/fufaeff/ha-aecc-cloud/actions/workflows/validate.yml/badge.svg)](https://github.com/fufaeff/ha-aecc-cloud/actions/workflows/validate.yml)
[![GitHub Release](https://img.shields.io/github/v/release/fufaeff/ha-aecc-cloud)](https://github.com/fufaeff/ha-aecc-cloud/releases)

Home Assistant custom integration for inverters, batteries and devices connected to
**AEC Cloud** (AI Energy Controller, `monitor.ai-ec.cloud`).

> Unofficial integration. Not affiliated with or endorsed by AECC.
> **Use at your own risk** — see [Disclaimer](#disclaimer).

## Features

* Power flow telemetry: solar, battery charge/discharge, grid, load, daily/total energy,
  plus every value the inverter reports to the cloud.
* Calculated energy sensors (kWh) for solar, total load, battery charge and discharge —
  restored after restart, ready for the **Energy dashboard**.
* Inverter settings, written the same way as the official AECC app:
  * **Output Priority**: SBU/PBG, SUB/PGB, USB/GPB, MKS (generator first)
  * **Charging Priority**: CSO/PVF, SNU/PNG, OSO/OPV
  * Mains / maximum charging current, buzzer mute
  * SOC thresholds for switching to mains / battery and low-SOC shutdown
* Smart sockets, EV chargers and power controllers (on/off).
* Services: `set_working_mode`, `set_charger_priority`, `set_energy_counter`, `switch_plant`.

Details, entity list, value tables and API notes:
[custom_components/aecc_cloud_plugin/README.md](custom_components/aecc_cloud_plugin/README.md).

Tested with an SP100-12000-48 (AN-FGI-S12000) hybrid inverter and a W5C Wi-Fi datalogger.

## Installation

### HACS (recommended)

1. Open **HACS** → menu (⋮) → **Custom repositories**.
2. Add `https://github.com/fufaeff/ha-aecc-cloud`, category **Integration**.
3. Find **AECC Cloud** in HACS and click **Download**.
4. Restart Home Assistant.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=fufaeff&repository=ha-aecc-cloud&category=integration)

### Manual

Copy `custom_components/aecc_cloud_plugin` into the `custom_components` folder of your
Home Assistant configuration directory and restart Home Assistant.

## Configuration

1. **Settings** → **Devices & Services** → **Add Integration** → **AECC Cloud**.
2. Enter your AEC Cloud account email and password.
3. Select the plant to monitor.

Data is polled every minute; the inverter itself uploads to the cloud every 5 minutes.

## Troubleshooting

Enable debug logging:

```yaml
logger:
  logs:
    custom_components.aecc_cloud_plugin: debug
```

Auth tokens and cookies are masked in the log, but it still contains serial numbers
and plant data — review it before attaching to an issue.

## Disclaimer

This integration is provided **"as is", without warranty of any kind**, and is used
**entirely at your own risk**.

* It is an unofficial project, not developed, supported or endorsed by AECC. The AEC Cloud
  API is undocumented and may change or stop working at any time.
* It can change inverter settings (output and charging priority, charging currents,
  SOC thresholds). Wrong settings may lead to power outages, battery damage, equipment
  damage, higher energy costs or loss of warranty. Make sure you understand every setting
  before changing it and check the result on the inverter.
* The author accepts **no responsibility or liability** for any direct or indirect damage,
  loss of data, equipment failure, financial loss or any other consequences resulting
  from installing or using this integration.

By installing and using this integration you confirm that you have read and accepted
these terms.

## License

[MIT](LICENSE)
