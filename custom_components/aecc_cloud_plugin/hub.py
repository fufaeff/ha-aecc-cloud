import asyncio
import hashlib
import json
import logging
import re
import time
from datetime import timedelta, datetime
from typing import Any, Optional

import aiohttp
from aiohttp import ContentTypeError

from .const import BASE_URL, API_URL
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval

_LOGGER = logging.getLogger(__name__)

_SENSITIVE_HEADERS = {"token", "authorization", "cookie"}

# Headers the official AECC app sends to api.ai-ec.cloud
_API_HEADERS = {"InterfaceType": "2", "projectType": "1", "appVersion": "1.261010.2"}
SETTINGS_REFRESH_SEC = 300

OUTPUT_PRIORITY_FIELD = "outputPriority2"   # register 0x4102: 0=GPB 1=PGB 2=PBG 3=MKS (generator first)
CHARGE_PRIORITY_FIELD = "chargePriority2"   # register 0x4104: 0=PNG 1=OPV 2=PVF

_OUTPUT_ALIASES = {"USB": "GPB", "SUB": "PGB", "SBU": "PBG"}
_CHARGE_ALIASES = {"SNU": "PNG", "OSO": "OPV", "CSO": "PVF"}


def _code_from(text: str, codes: tuple, aliases: dict) -> Optional[str]:
    """Pick the first 3-letter token in text that is a known code or legacy alias."""
    for token in re.findall(r"[A-Z]{3}", str(text).upper()):
        if token in codes:
            return token
        if token in aliases:
            return aliases[token]
    return None


def output_priority_code(text: str) -> Optional[str]:
    return _code_from(text, ("GPB", "PGB", "PBG", "MKS"), _OUTPUT_ALIASES)


def charge_priority_code(text: str) -> Optional[str]:
    return _code_from(text, ("PNG", "OPV", "PVF"), _CHARGE_ALIASES)
_LOG_BODY_LIMIT = 300


def _redact_headers(headers: Optional[dict]) -> dict:
    """Return a copy of headers safe for logging (auth tokens and cookies masked)."""
    if not headers:
        return {}
    return {
        k: ("***" if str(k).lower() in _SENSITIVE_HEADERS else v)
        for k, v in headers.items()
    }


def _resp_summary(resp: Any) -> str:
    """Short, token-free description of an API response for logging."""
    if isinstance(resp, dict):
        return f"result={resp.get('result')!r}, msg={resp.get('msg')!r}"
    return f"{type(resp).__name__}"


def is_md5(value: str) -> bool:
    """True if value already looks like an MD5 hex digest."""
    return len(value) == 32 and all(c in "0123456789abcdefABCDEF" for c in value)


def md5_hash(password: str) -> str:
    """Return an MD5 hash for the given password if not already hashed."""
    if is_md5(password):
        return password.lower()
    hasher = hashlib.md5()
    hasher.update(password.encode('utf-8'))
    return hasher.hexdigest()


class MyIntegrationHub:
    def __init__(self, hass, username, password, senceId):
        self._entities = []
        self.senceId = senceId
        self.hass = hass
        self.devices_info: dict[str, list[Any]] = {}
        self._username = username
        self._password = password
        self._session = async_get_clientsession(self.hass)
        self._unsub_polling = None
        self._unsub_login = None
        self.total_data = {}
        self.device_data: dict[str, Any] = {}
        self.plants = []
        self.settings_info: dict[str, dict] = {}
        # Per config entry: set by async_setup_entry
        self.device_manager = None
        self.plant_name: str = str(senceId)
        self._ai_cache: Optional[dict] = None
        self._ai_ts = 0.0
        self._login_lock = asyncio.Lock()
        self._last_login_time = 0.0
        self._token: Optional[str] = None

    def _get_headers(self, custom_headers: Optional[dict] = None) -> dict:
        """Construct request headers with language preference and authorization token."""
        headers = dict(custom_headers) if custom_headers else {}
        headers.setdefault('Accept-Language', 'en-US')
        if self._token:
            headers.setdefault('token', self._token)
            headers.setdefault('Token', self._token)
        return headers

    async def login(self, now=None):
        """Execute login operation with concurrency lock and debouncing."""
        async with self._login_lock:
            # If recently authenticated within last 15 seconds, reuse existing fresh session
            if time.monotonic() - self._last_login_time < 15:
                return True
            _LOGGER.info("Starting login to AEC Cloud")
            return await self._login(self._username, self._password)

    async def _login(self, username, password):
        """Perform login request with retries, JWT token extraction, and fresh session cookies."""
        url = BASE_URL + "/user/login"
        self._session = async_get_clientsession(self.hass)

        # Clear expired cookies for domain to prevent server from rejecting login with stale session
        try:
            self._session.cookie_jar.clear_domain("monitor.ai-ec.cloud")
        except Exception:
            pass

        headers = {'Content-Type': 'application/json', 'Accept-Language': 'en-US'}
        hash_pwd = md5_hash(password)
        req = {
            "email": username,
            "password": hash_pwd,
            "phoneOs": 1,
            "phoneModel": "1.1",
            "appVersion": "V1.1"
        }
        json_data = json.dumps(req)

        for attempt in range(1, 4):
            try:
                timeout = aiohttp.ClientTimeout(total=15)
                async with self._session.post(url, headers=headers, data=json_data, timeout=timeout) as resp:
                    if resp.status == 200:
                        self._session.cookie_jar.update_cookies(resp.cookies)
                        text = await resp.text()
                        try:
                            resp_data = json.loads(text)
                        except Exception:
                            resp_data = {}

                        _LOGGER.debug(f"Login attempt {attempt} response: {_resp_summary(resp_data)}")

                        # AEC Cloud returns result: 0 or result: 1 or msg: 'Login successfully.'
                        is_success = (
                            isinstance(resp_data, dict)
                            and (
                                resp_data.get('result') in (0, 1, "0", "1")
                                or "success" in str(resp_data.get('msg', '')).lower()
                            )
                        )
                        if is_success:
                            # Extract JWT token if present
                            obj_data = resp_data.get('obj') if isinstance(resp_data.get('obj'), dict) else {}
                            self._token = resp_data.get('token') or obj_data.get('token')
                            self._last_login_time = time.monotonic()
                            _LOGGER.info("Successfully authenticated with AEC Cloud")
                            return True
                        else:
                            _LOGGER.warning(f"Login attempt {attempt} returned non-success result: {_resp_summary(resp_data)}")
                    else:
                        _LOGGER.warning(f"Login attempt {attempt} failed with HTTP status {resp.status}")
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                _LOGGER.warning(f"Login attempt {attempt} network exception: {err}")
            except Exception as err:
                _LOGGER.warning(f"Login attempt {attempt} unexpected error: {err}")

            if attempt < 3:
                await asyncio.sleep(1.5 * attempt)

        _LOGGER.error("Re-login to AEC Cloud failed after 3 attempts")
        return False

    async def start_polling(self):
        """Start periodic polling timer."""
        await self.stop_polling()
        update_interval = timedelta(minutes=1)
        self._unsub_polling = async_track_time_interval(
            self.hass,
            self.async_update_data,
            update_interval
        )
        await self.async_update_data()

    async def stop_polling(self):
        """Stop periodic polling timer."""
        if self._unsub_polling:
            self._unsub_polling()
            self._unsub_polling = None

    async def start_schedule_login(self):
        """Start scheduled token refresh timer."""
        await self.stop_schedule_login()
        update_interval = timedelta(hours=8)
        self._unsub_login = async_track_time_interval(
            self.hass,
            self.login,
            update_interval
        )

    async def stop_schedule_login(self):
        """Stop scheduled token refresh timer."""
        if self._unsub_login:
            self._unsub_login()
            self._unsub_login = None

    def add_entity(self, entity):
        """Register entity for data updates."""
        self._entities.append(entity)

    async def async_update_data(self, now=None):
        """Perform data update operation for all registered entities."""
        _LOGGER.debug("Starting data update")
        start_time = datetime.now()
        try:
            await self.getPlantVos()
            new_data = await self.getHomeCountData()
            # Query detailed device data by SN (each SN only once per cycle:
            # the master device often shares its SN with the storage device)
            fetched_sns = set()
            for device in getattr(self.device_manager, "devices", []):
                if device.type != -1:
                    if device.device_sn in fetched_sns:
                        continue
                    fetched_sns.add(device.device_sn)
                    _LOGGER.debug(f"Updating device: type={device.type}, sn={device.device_sn}")
                    res = await self.fetch_device_info(device.type, device.device_sn)
                    if res and "displayMap" in res:
                        self.devices_info[device.device_sn] = res["displayMap"]

            # Inverter settings (Output/Charging Priority etc.), refreshed every SETTINGS_REFRESH_SEC
            try:
                await self.fetch_setting_info()
            except Exception as err:
                _LOGGER.debug(f"Setting info refresh failed: {err}")

            if new_data:
                ai = await self.get_ai_system_cached()
                for entity in self._entities:
                    # One broken entity must not stop updates of all others
                    try:
                        entity.update_data(new_data, self.devices_info, ai)
                    except Exception as err:
                        _LOGGER.warning(f"Update of {getattr(entity, 'entity_id', entity)} failed: {err}")

        except Exception as e:
            _LOGGER.error(f"Exception during update (line {e.__traceback__.tb_lineno}): {e}")

        end_time = datetime.now()
        _LOGGER.debug(f"Data update completed in {end_time - start_time}")

    async def getHomeCountData(self):
        """Fetch home energy flow telemetry data."""
        url = BASE_URL + "/energy/getHomeCountData?plantId=" + str(self.senceId)
        resp = await self.post({}, url, {})
        _LOGGER.debug(f"Energy flow response: {_resp_summary(resp)}")
        if resp and isinstance(resp, dict) and 'obj' in resp:
            res = resp['obj']
            self.total_data = res
            return res
        return {}

    async def getPlantVos(self):
        """Fetch all plants for the authenticated user."""
        url = BASE_URL + "/plant/getPlantVos"
        resp = await self.get({}, url, {})
        _LOGGER.debug(f"Plant response: {_resp_summary(resp)}")
        if resp and isinstance(resp, dict) and 'obj' in resp:
            res = resp['obj']
            self.plants = res
            return res
        return []

    async def getAiSystemByPlantId(self):
        """Fetch AI mode details for the plant."""
        url = BASE_URL + "/aiSystem/getAiSystemByPlantId"
        resp = await self.get({}, url, params={"plantId": str(self.senceId)})
        _LOGGER.debug(f"AI mode response: {_resp_summary(resp)}")
        if resp and isinstance(resp, dict) and 'obj' in resp:
            return resp['obj']
        return {}

    async def get_ai_system_cached(self) -> dict:
        """AI system settings change rarely: refresh at most every SETTINGS_REFRESH_SEC."""
        if self._ai_cache is None or time.monotonic() - self._ai_ts >= SETTINGS_REFRESH_SEC:
            ai = await self.getAiSystemByPlantId()
            if ai or self._ai_cache is None:
                self._ai_cache = ai or {}
            self._ai_ts = time.monotonic()
        return self._ai_cache

    async def fetch_device_info(self, device_type, device_sn):
        """Fetch detailed device parameters by SN."""
        url = BASE_URL + "/device/getDeviceBySn"
        today = datetime.now().strftime("%Y-%m-%d")
        resp = await self.post(
            {'Accept-Language': 'en-US'},
            url,
            params={
                'deviceType': device_type,
                'time': today,
                'sn': device_sn,
            }
        )
        _LOGGER.debug(f"Device details response for {device_sn}: {_resp_summary(resp)}")
        if resp and isinstance(resp, dict) and 'obj' in resp and resp['obj'] is not None:
            res = resp['obj']
            res['chartMap'] = None
            self.device_data[device_sn] = res
            return res
        return {}

    async def switch_socket(self, sn: str, value: int):
        """Send switch parameter to smart socket."""
        url = BASE_URL + "/device/setDeviceParam"
        resp = await self.post(
            {'Content-Type': 'application/x-www-form-urlencoded'},
            url,
            {
                'deviceSn': sn,
                'startAddr': 0x0000,
                'data': value,
            }
        )
        _LOGGER.info(f"Socket switch command response: {resp}")
        return resp.get('msg') if resp else None

    async def switch_charger(self, sn: str, value: int):
        """Send switch parameter to EV charger."""
        url = BASE_URL + "/device/setDeviceParam"
        resp = await self.post(
            {'Content-Type': 'application/x-www-form-urlencoded'},
            url,
            {
                'deviceSn': sn,
                'startAddr': 0x00AF,
                'data': value,
            }
        )
        _LOGGER.info(f"Charger switch command response: {resp}")
        return resp.get('msg') if resp else None

    async def switch_product(self, sn: str, value: int):
        """Send switch status to generic energy product."""
        url = BASE_URL + "/energyProduct/setEnergyProductSwitch"
        resp = await self.post(
            {},
            url,
            params={
                "deviceSn": sn,
                "switchStatus": value
            }
        )
        _LOGGER.info(f"Product switch command response: {resp}")
        return resp.get('msg') if resp else None

    def get_device_and_datalog_sn(self, requested_sn: Optional[str] = None) -> tuple[Optional[str], Optional[str]]:
        """Resolve inverter device SN and datalogger SN."""
        target_sn = requested_sn if (requested_sn and requested_sn != "master") else None
        datalog_sn = None

        if hasattr(self, "device_data") and self.device_data:
            for s_sn, d_val in self.device_data.items():
                if isinstance(d_val, dict):
                    if not target_sn and s_sn and s_sn != "master":
                        target_sn = s_sn
                    if d_val.get("datalogSn"):
                        datalog_sn = d_val.get("datalogSn")
                    if target_sn and datalog_sn:
                        break

        if not datalog_sn and hasattr(self, "devices_info") and self.devices_info:
            for s_sn, d_map in self.devices_info.items():
                if isinstance(d_map, dict):
                    if not target_sn and s_sn and s_sn != "master":
                        target_sn = s_sn
                    if d_map.get("datalog sn") or d_map.get("datalogSn"):
                        datalog_sn = d_map.get("datalog sn") or d_map.get("datalogSn")
                    if target_sn and datalog_sn:
                        break

        if not target_sn and hasattr(self, "total_data") and self.total_data:
            target_sn = self.total_data.get("solarSn") or self.total_data.get("deviceSn")
            if not datalog_sn:
                datalog_sn = self.total_data.get("datalogSn")

        return target_sn, datalog_sn

    @staticmethod
    def _is_success_response(resp: Any) -> bool:
        """Check if an AEC Cloud API response indicates success."""
        if not resp or not isinstance(resp, dict):
            return False
        msg = str(resp.get("msg", "")).lower()
        if any(err_word in msg for err_word in ("error", "fail", "cannot be empty", "invalid", "offline", "missing")):
            return False
        if resp.get("result") in (0, "0", 200, "200"):
            return True
        if "success" in msg:
            return True
        return False

    def _resolve_inverter(self, device_sn: Optional[str] = None) -> tuple[Optional[str], Optional[str]]:
        """Resolve inverter SN + datalogger SN, falling back to auto-detection if SN is unknown."""
        sn, dl = self.get_device_and_datalog_sn(device_sn)
        if sn not in self.device_data:
            sn, dl = self.get_device_and_datalog_sn(None)
        if not dl and isinstance(self.device_data.get(sn), dict):
            dl = self.device_data[sn].get("datalogSn")
        return sn, dl

    async def fetch_setting_info(self, device_sn: Optional[str] = None, force: bool = False) -> dict:
        """Fetch the inverter settings template (/deviceSetConfig/getSettingInfo).

        Returns {fieldName: item}; each item carries masterId, slaveId, sendType,
        current cellVal and componentObj.choiceParamArr (allowed values).
        Cached for SETTINGS_REFRESH_SEC.
        """
        sn, dl = self._resolve_inverter(device_sn)
        dev = self.device_data.get(sn) or {}
        dtc = dev.get("dtc")
        if not sn or dtc is None:
            return {}

        cached = self.settings_info.get(sn)
        if cached and not force and time.monotonic() - cached["ts"] < SETTINGS_REFRESH_SEC:
            return cached["fields"]

        resp = await self.get(
            _API_HEADERS,
            API_URL + "/deviceSetConfig/getSettingInfo",
            params={"dtc": str(dtc), "displayType": "2", "deviceSn": sn, "datalogSn": dl or ""},
        )
        fields: dict[str, dict] = {}
        if isinstance(resp, dict) and isinstance(resp.get("obj"), list):
            for group in resp["obj"]:
                for item in (group or {}).get("settingSmallData") or []:
                    name = item.get("fieldName")
                    if name and name not in fields:
                        fields[name] = item
        _LOGGER.debug(f"Setting info for {sn}: {_resp_summary(resp)}, {len(fields)} fields")

        if fields:
            self.settings_info[sn] = {"ts": time.monotonic(), "fields": fields}
            return fields
        return cached["fields"] if cached else {}

    def get_setting_choice(self, field_name: str, device_sn: Optional[str] = None) -> Optional[str]:
        """Return the choice name (e.g. 'PGB') of the cached current value of a setting."""
        sn, _ = self._resolve_inverter(device_sn)
        item = ((self.settings_info.get(sn) or {}).get("fields") or {}).get(field_name)
        if not item or item.get("cellVal") is None:
            return None
        cur = str(item.get("cellVal"))
        for choice in (item.get("componentObj") or {}).get("choiceParamArr") or []:
            if str(choice.get("val")) == cur:
                return str(choice.get("name"))
        return None

    def get_setting_item(self, field_name: str, device_sn: Optional[str] = None) -> Optional[dict]:
        """Cached settings template item for a field (None until getSettingInfo succeeded)."""
        sn, _ = self._resolve_inverter(device_sn)
        return ((self.settings_info.get(sn) or {}).get("fields") or {}).get(field_name)

    async def _get_setting_for_write(self, field_name: str, device_sn: Optional[str]) -> tuple:
        sn, dl = self._resolve_inverter(device_sn)
        fields = await self.fetch_setting_info(sn)
        item = fields.get(field_name)
        if not item:
            raise HomeAssistantError(f"Setting '{field_name}' is not available for device {sn}")
        return sn, dl, item

    async def set_custom_param(self, field_name: str, choice_name: str, device_sn: Optional[str] = None) -> bool:
        """Write a list-type inverter setting by choice name (e.g. 'PGB', '60A', 'On')."""
        sn, dl, item = await self._get_setting_for_write(field_name, device_sn)
        choices = (item.get("componentObj") or {}).get("choiceParamArr") or []
        val = next(
            (str(c.get("val")) for c in choices if str(c.get("name")).upper() == choice_name.upper()),
            None,
        )
        if val is None:
            allowed = ", ".join(str(c.get("name")) for c in choices)
            raise HomeAssistantError(
                f"'{choice_name}' is not a valid value for {item.get('cellName')} (allowed: {allowed})"
            )
        return await self._write_setting(sn, dl, item, field_name, val, choice_name)

    async def set_custom_value(self, field_name: str, value: str, device_sn: Optional[str] = None) -> bool:
        """Write an input-type inverter setting (e.g. SOC %), validated by the server-provided regexp."""
        sn, dl, item = await self._get_setting_for_write(field_name, device_sn)
        regexp = ((item.get("componentObj") or {}).get("inputRegexp") or {}).get("regexpTxt")
        if regexp and not re.fullmatch(regexp, value):
            tip = (item.get("componentObj") or {}).get("inputCustomTipTxt") or regexp
            raise HomeAssistantError(f"{value} is out of range for {item.get('cellName')} ({tip})")
        return await self._write_setting(sn, dl, item, field_name, value, value)

    async def _write_setting(self, sn, dl, item: dict, field_name: str, val: str, label: str) -> bool:
        """POST /deviceSetConfig/setCustomParams the same way the AECC app does."""
        dev = self.device_data.get(sn) or {}
        payload = {
            "deviceSn": sn,
            "datalogSn": dl,
            "deviceType": dev.get("deviceType"),
            "masterId": item.get("masterId"),
            "slaveId": item.get("slaveId"),
            "dtc": item.get("dtc", dev.get("dtc")),
            "sendType": item.get("sendType", 0),
            "object": {field_name: val},
        }
        headers = dict(_API_HEADERS)
        headers["Content-Type"] = "application/json;charset=UTF-8"
        _LOGGER.info(f"[AECC Settings] {item.get('cellName')}: {field_name}={val} ({label}) for {sn}")
        resp = await self.post(headers, API_URL + "/deviceSetConfig/setCustomParams", data=json.dumps(payload))

        if self._is_success_response(resp):
            item["cellVal"] = val
            _LOGGER.info(f"[AECC Settings] {field_name}={val} accepted: {_resp_summary(resp)}")
            return True
        _LOGGER.warning(f"[AECC Settings] {field_name}={val} rejected: {_resp_summary(resp)}")
        return False

    async def set_working_mode(self, mode: str, device_sn: Optional[str] = None) -> bool:
        """Set inverter Output Priority (GPB/PGB/PBG/MKS; legacy USB/SUB/SBU accepted)."""
        code = output_priority_code(mode)
        if not code:
            raise HomeAssistantError(f"Unknown output priority: {mode}")
        return await self.set_custom_param(OUTPUT_PRIORITY_FIELD, code, device_sn)

    async def set_charger_priority(self, mode: str, device_sn: Optional[str] = None) -> bool:
        """Set inverter Charging Priority (PNG/OPV/PVF; legacy SNU/OSO/CSO accepted)."""
        code = charge_priority_code(mode)
        if not code:
            raise HomeAssistantError(
                f"Unsupported charging priority: {mode} (inverter supports PNG/SNU, OPV/OSO, PVF/CSO)"
            )
        return await self.set_custom_param(CHARGE_PRIORITY_FIELD, code, device_sn)

    async def post(self, headers, url, data=None, params=None, is_retry: bool = False, suppress_warnings: bool = False):
        """Generic POST request with auto-relogin, JWT token, and timeout."""
        req_headers = self._get_headers(headers)
        _LOGGER.debug(f"[HTTP POST REQUEST] URL: {url} | params: {params} | data: {data} | headers: {_redact_headers(req_headers)}")
        try:
            timeout = aiohttp.ClientTimeout(total=25)
            async with self._session.post(url, headers=req_headers, params=params, data=data, timeout=timeout) as resp:
                _LOGGER.debug(f"[HTTP POST STATUS] URL: {url} -> HTTP {resp.status}")
                if resp.status == 200:
                    self._session.cookie_jar.update_cookies(resp.cookies)
                    text = await resp.text()
                    _LOGGER.debug(f"[HTTP POST BODY] URL: {url} -> {len(text)} bytes: {text[:_LOG_BODY_LIMIT]}")
                    try:
                        resp_data = json.loads(text)
                    except Exception:
                        resp_data = text
                        _LOGGER.warning(f"Non-JSON response from {url}: {resp_data}")

                    if isinstance(resp_data, dict):
                        result_val = resp_data.get("result")
                        values_str = str(resp_data.values())
                        msg_val = str(resp_data.get("msg", ""))
                        if (
                            result_val in (10000, "10000")
                            or "请登录" in values_str
                            or "Please login" in values_str
                            or "Please login" in msg_val
                        ):
                            if not is_retry:
                                _LOGGER.warning(f"Session expired during POST {url}, re-authenticating...")
                                logged_in = await self.login()
                                if logged_in:
                                    _LOGGER.info(f"Re-login successful, retrying POST request to {url}...")
                                    return await self.post(headers, url, data=data, params=params, is_retry=True, suppress_warnings=suppress_warnings)
                                else:
                                    _LOGGER.error(f"Re-login to AEC Cloud failed for {url}")
                            return None
                    return resp_data
                else:
                    text_err = await resp.text()
                    _LOGGER.debug(f"[HTTP POST ERROR BODY] URL: {url} (HTTP {resp.status}) -> {text_err[:500]}")
                    if suppress_warnings:
                        _LOGGER.debug(f"Request to {url} returned HTTP status: {resp.status}")
                    else:
                        _LOGGER.warning(f"Failed to fetch data from {url}, HTTP status: {resp.status}")
                    return None
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            _LOGGER.debug(f"[HTTP POST EXCEPTION] Network error during POST {url}: {err}")
            if suppress_warnings:
                _LOGGER.debug(f"Network error during POST {url}: {err}")
            else:
                _LOGGER.warning(f"Network error during POST {url}: {err}")
            return None
        except Exception as err:
            _LOGGER.debug(f"[HTTP POST EXCEPTION] Unexpected error during POST {url}: {err}", exc_info=True)
            if suppress_warnings:
                _LOGGER.debug(f"Unexpected error during POST {url}: {err}")
            else:
                _LOGGER.warning(f"Unexpected error during POST {url}: {err}")
            return None

    async def get(self, headers, url, data=None, params=None, is_retry: bool = False, suppress_warnings: bool = False):
        """Generic GET request with auto-relogin, JWT token, and timeout."""
        req_headers = self._get_headers(headers)
        _LOGGER.debug(f"[HTTP GET REQUEST] URL: {url} | params: {params} | headers: {_redact_headers(req_headers)}")
        try:
            timeout = aiohttp.ClientTimeout(total=25)
            async with self._session.get(url, headers=req_headers, params=params, data=data, timeout=timeout) as resp:
                _LOGGER.debug(f"[HTTP GET STATUS] URL: {url} -> HTTP {resp.status}")
                if resp.status == 200:
                    self._session.cookie_jar.update_cookies(resp.cookies)
                    text = await resp.text()
                    _LOGGER.debug(f"[HTTP GET BODY] URL: {url} -> {len(text)} bytes: {text[:_LOG_BODY_LIMIT]}")
                    try:
                        resp_data = json.loads(text)
                    except Exception:
                        resp_data = text
                        _LOGGER.warning(f"Non-JSON response from {url}: {resp_data}")

                    if isinstance(resp_data, dict):
                        result_val = resp_data.get("result")
                        values_str = str(resp_data.values())
                        msg_val = str(resp_data.get("msg", ""))
                        if (
                            result_val in (10000, "10000")
                            or "请登录" in values_str
                            or "Please login" in values_str
                            or "Please login" in msg_val
                        ):
                            if not is_retry:
                                _LOGGER.warning(f"Session expired during GET {url}, re-authenticating...")
                                logged_in = await self.login()
                                if logged_in:
                                    _LOGGER.info(f"Re-login successful, retrying GET request to {url}...")
                                    return await self.get(headers, url, data=data, params=params, is_retry=True, suppress_warnings=suppress_warnings)
                                else:
                                    _LOGGER.error(f"Re-login to AEC Cloud failed for {url}")
                            return None
                    return resp_data
                else:
                    if suppress_warnings:
                        _LOGGER.debug(f"Request to {url} returned HTTP status: {resp.status}")
                    else:
                        _LOGGER.warning(f"Failed to fetch data from {url}, HTTP status: {resp.status}")
                    return None
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            if suppress_warnings:
                _LOGGER.debug(f"Network error during GET {url}: {err}")
            else:
                _LOGGER.warning(f"Network error during GET {url}: {err}")
            return None
        except Exception as err:
            if suppress_warnings:
                _LOGGER.debug(f"Unexpected error during GET {url}: {err}")
            else:
                _LOGGER.warning(f"Unexpected error during GET {url}: {err}")
            return None
