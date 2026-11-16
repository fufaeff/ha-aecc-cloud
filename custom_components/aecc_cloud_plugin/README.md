# AECC Cloud (`aecc_cloud_plugin`)

Home Assistant integration for inverters and devices connected to **AEC Cloud**.
It polls the cloud every minute and writes inverter settings the same way as the
official AECC mobile app.

> Unofficial integration, provided "as is" and used **at your own risk**. The author
> accepts no responsibility for any damage or loss caused by its use — see the
> [Disclaimer](../../README.md#disclaimer).

## Entities

| Platform | Entities |
|---|---|
| `sensor` | Plant power flow (solar, battery, grid, load), daily/total energy, statuses, all values from the inverter `displayMap` |
| `sensor` (calculated) | `Total Load Energy`, `Solar Energy`, `Battery Charge Energy`, `Battery Discharge Energy` — kWh integrated from power (Riemann sum), restored after restart, suitable for the Energy dashboard |
| `select` | `Working Mode` (Output Priority), `Charger Source Priority` (Charging Priority), `Active Plant` |
| `select` | `Mains Charging Current`, `Maximum Charging Current`, `Mute Buzzer` |
| `number` | `SOC for Switching to Mains`, `SOC for Switching to Battery`, `Low SOC Shutdown` |
| `switch` | Smart sockets, EV chargers, power controllers |

Setting entities become available after the first successful
`getSettingInfo` request (shortly after start). Allowed values are taken from the
cloud, so they match what the app shows for your inverter.

### Output Priority (register `0x4102`, field `outputPriority2`)

| Select option | Code | Meaning |
|---|---|---|
| `SBU (Solar -> Battery -> Utility)` | PBG | PV → battery → grid |
| `SUB (Solar -> Utility -> Battery)` | PGB | PV → grid → battery |
| `USB (Utility -> Solar -> Battery)` | GPB | grid → PV → battery |
| `MKS (Generator first)` | MKS | generator first; with generator + PV + battery works as PBG, with generator + PV or battery as GPB |

### Charging Priority (register `0x4104`, field `chargePriority2`)

| Select option | Code | Meaning |
|---|---|---|
| `CSO (Solar first / Приоритет солнце)` | PVF | PV first |
| `SNU (Solar and Utility / Солнце и сеть)` | PNG | PV and grid |
| `OSO (Only Solar / Только солнце)` | OPV | PV only |

After a successful write the select keeps the chosen value for 6 minutes: the
inverter uploads telemetry every 5 minutes, so the cloud may still report the old
value. If the cloud rejects a write, Home Assistant shows an error and the select
keeps the real value.

## Services

| Service | Purpose |
|---|---|
| `set_working_mode` | Set Output Priority. `mode` accepts the select option or a code (`PBG`, `PGB`, `GPB`, `MKS`, `SBU`, `SUB`, `USB`) |
| `set_charger_priority` | Set Charging Priority. `mode` accepts the select option or a code (`PVF`, `PNG`, `OPV`, `CSO`, `SNU`, `OSO`) |
| `set_energy_counter` | Set a calculated energy sensor to `value` kWh (default 0) — reset it or align it with the inverter's lifetime counter |
| `switch_plant` | Switch the monitored plant (`plant_id`) |

Example:

```yaml
action: aecc_cloud_plugin.set_working_mode
data:
  mode: PBG
```

```yaml
action: aecc_cloud_plugin.set_energy_counter
target:
  entity_id: sensor.total_load_energy
data:
  value: 71.63
```

## Cloud API used

| Purpose | Request |
|---|---|
| Login | `POST monitor.ai-ec.cloud:8443/user/login` |
| Plants, power flow, device data | `monitor.ai-ec.cloud:8443` — `/plant/getPlantVos`, `/energy/getHomeCountData`, `/device/getDeviceBySn` |
| Settings template and current values | `GET api.ai-ec.cloud:8443/deviceSetConfig/getSettingInfo?dtc=…&displayType=2&deviceSn=…&datalogSn=…` (cached 5 min) |
| Write a setting | `POST api.ai-ec.cloud:8443/deviceSetConfig/setCustomParams` with `deviceSn`, `datalogSn`, `deviceType`, `masterId`, `slaveId`, `dtc`, `sendType`, `object: {fieldName: value}` |

Auth tokens and cookies are masked in debug logs.
