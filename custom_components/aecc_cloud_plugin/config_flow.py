"""Config flow for AECC Cloud integration."""
from __future__ import annotations

import json
import hashlib
import logging
import voluptuous as vol
from homeassistant import config_entries, exceptions

from .const import DOMAIN, BASE_URL  # pylint:disable=unused-import
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema({"username": str, "password": str})


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for AECC Cloud."""

    VERSION = 1

    def __init__(self):
        self.data = {}
        self.devices = {}

    async def async_step_user(self, user_input=None):
        errors = {}

        if user_input is not None:
            try:
                username = user_input['username'].strip()
                hash_pwd = self.md5_hash(user_input['password'])
                await self._login(username, hash_pwd)
                # Store only the MD5 hash: it is all the cloud needs
                self.data.update({"username": username, "password": hash_pwd})
                return await self.async_step_select_device()
            except Exception as err:
                _LOGGER.error(f"Login error: {err}")
                errors["base"] = "login_error"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("username"): str,
                vol.Required("password"): str,
            }),
            errors=errors,
        )

    async def async_step_select_device(self, user_input=None):
        if user_input is not None:
            selected_device_id = user_input["devices"]
            selected_device_name = self.devices[selected_device_id]

            # One entry per account + plant
            await self.async_set_unique_id(f"{self.data['username'].lower()}_{selected_device_id}")
            self._abort_if_unique_id_configured()

            self.data.update({
                "selected_device_id": selected_device_id,
                "selected_device_name": selected_device_name
            })
            return self.async_create_entry(title=f"AECC Cloud - {selected_device_name}", data=self.data)

        try:
            self.devices = await self._fetch_devices()
        except Exception as err:
            _LOGGER.error(f"Device fetch error: {err}")
            return self.async_abort(reason="device_fetch_error")

        return self.async_show_form(
            step_id="select_device",
            data_schema=vol.Schema({
                vol.Required("devices"): vol.In(self.devices),
            }),
        )

    def md5_hash(self, password: str) -> str:
        """Return an MD5 hash for the given password."""
        hasher = hashlib.md5()
        hasher.update(password.encode('utf-8'))
        return hasher.hexdigest()

    async def _login(self, username: str, password: str) -> bool:
        url = f"{BASE_URL}/user/login"
        session = async_get_clientsession(self.hass)
        headers = {'Content-Type': 'application/json'}
        req = {"email": username, "password": password, "phoneOs": 1, "phoneModel": "1.1", "appVersion": "V1.1"}
        json_data = json.dumps(req)

        async with session.post(url, headers=headers, data=json_data) as resp:
            if resp.status == 200:
                text = await resp.text()
                _LOGGER.debug("Login response received (%d bytes)", len(text))
                session.cookie_jar.update_cookies(resp.cookies)
                try:
                    res_json = json.loads(text)
                    if isinstance(res_json, dict) and res_json.get("result") not in (0, 1, "0", "1") and "success" not in str(res_json.get("msg", "")).lower():
                        msg = res_json.get("msg", "Authentication failed")
                        raise Exception(f"Login failed: {msg}")
                except (json.JSONDecodeError, TypeError):
                    pass
                return True
            else:
                raise Exception("Failed to login")

    async def _fetch_devices(self) -> dict:
        url = f"{BASE_URL}/plant/getPlantVos"
        session = async_get_clientsession(self.hass)

        async with session.get(url) as resp:
            if resp.status == 200:
                session.cookie_jar.update_cookies(resp.cookies)
                text = await resp.text()
                try:
                    devices = json.loads(text)
                except Exception as err:
                    raise Exception(f"Failed to parse device list: {err}")
                if not isinstance(devices, dict) or 'obj' not in devices:
                    raise Exception(f"Invalid device response: {devices}")
                return {str(item["id"]): item["plantName"] for item in devices['obj']}
            else:
                raise Exception("Failed to fetch devices")


class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidHost(exceptions.HomeAssistantError):
    """Error to indicate there is an invalid hostname."""
