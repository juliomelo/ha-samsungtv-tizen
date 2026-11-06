"""Config flow for the samsungtv component."""
import json
import logging
import os
import socket
from urllib.parse import urlparse

from aiohttp import ClientError, ClientTimeout
import probatio
from websocket import WebSocketException

from homeassistant.config_entries import ConfigFlow, OptionsFlowWithReload
from homeassistant.const import (
    CONF_API_KEY,
    CONF_BROADCAST_ADDRESS,
    CONF_DEVICE_ID,
    CONF_HOST,
    CONF_MAC,
    CONF_NAME,
    CONF_PORT,
    CONF_TIMEOUT,
    CONF_TOKEN,
)
from homeassistant.core import callback
from homeassistant.data_entry_flow import AbortFlow
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from . import exceptions
from .const import (
    CONF_APP_LIST,
    CONF_CHANNEL_LIST,
    CONF_IS_FRAME_TV,
    CONF_MODEL,
    CONF_SCAN_APP_HTTP,
    CONF_SHOW_CHANNEL_NR,
    CONF_SHOW_LOGOS,
    CONF_SOURCE_LIST,
    CONF_UPDATE_CUSTOM_PING_URL,
    CONF_UPDATE_METHOD,
    DEFAULT_PORT,
    DEFAULT_SHOW_LOGOS,
    DEFAULT_SOURCE_LIST,
    DEFAULT_TIMEOUT,
    DEFAULT_UPDATE_METHOD,
    DOMAIN,
    MEDIA_IMAGE_OPTIONS,
    PAIRING_TIMEOUT,
)
from .websockets import SamsungTVWS

_LOGGER = logging.getLogger(__name__)

DEVICE_INFO_TIMEOUT = 5
DEVICE_TYPE_TV = "Samsung SmartTV"
INSECURE_PORT = 8001

USER_SCHEMA = probatio.Schema({probatio.Required(CONF_HOST): TextSelector()})

JSON_OPTIONS = (CONF_SOURCE_LIST, CONF_APP_LIST, CONF_CHANNEL_LIST)

OPTIONS_SCHEMA = probatio.Schema(
    {
        probatio.Optional(CONF_UPDATE_METHOD, default=DEFAULT_UPDATE_METHOD): SelectSelector(
            SelectSelectorConfig(
                options=["ping", "websockets", "smartthings"],
                mode=SelectSelectorMode.DROPDOWN,
            )
        ),
        probatio.Optional(CONF_UPDATE_CUSTOM_PING_URL): TextSelector(),
        probatio.Optional(CONF_TIMEOUT, default=DEFAULT_TIMEOUT): NumberSelector(
            NumberSelectorConfig(min=1, max=60, step=1, mode=NumberSelectorMode.BOX)
        ),
        probatio.Optional(CONF_BROADCAST_ADDRESS): TextSelector(),
        probatio.Optional(CONF_SOURCE_LIST, default=DEFAULT_SOURCE_LIST): TextSelector(
            TextSelectorConfig(multiline=True)
        ),
        probatio.Optional(CONF_APP_LIST): TextSelector(TextSelectorConfig(multiline=True)),
        probatio.Optional(CONF_CHANNEL_LIST): TextSelector(TextSelectorConfig(multiline=True)),
        probatio.Optional(CONF_SCAN_APP_HTTP, default=True): BooleanSelector(),
        probatio.Optional(CONF_IS_FRAME_TV, default=False): BooleanSelector(),
        probatio.Optional(CONF_SHOW_CHANNEL_NR, default=False): BooleanSelector(),
        probatio.Optional(CONF_SHOW_LOGOS, default=DEFAULT_SHOW_LOGOS): SelectSelector(
            SelectSelectorConfig(
                options=list(MEDIA_IMAGE_OPTIONS),
                mode=SelectSelectorMode.DROPDOWN,
            )
        ),
        probatio.Optional(CONF_DEVICE_ID): TextSelector(),
        probatio.Optional(CONF_API_KEY): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
    }
)

IMPORTED_OPTIONS = (
    CONF_UPDATE_METHOD,
    CONF_UPDATE_CUSTOM_PING_URL,
    CONF_TIMEOUT,
    CONF_BROADCAST_ADDRESS,
    CONF_SOURCE_LIST,
    CONF_APP_LIST,
    CONF_CHANNEL_LIST,
    CONF_SCAN_APP_HTTP,
    CONF_IS_FRAME_TV,
    CONF_SHOW_CHANNEL_NR,
    CONF_SHOW_LOGOS,
    CONF_DEVICE_ID,
    CONF_API_KEY,
)


def _read_legacy_token(host):
    """Return the token saved by the versions that kept it in a file."""
    path = os.path.join(os.path.dirname(os.path.realpath(__file__)), f"token-{host}.txt")
    try:
        with open(path, encoding="utf-8") as token_file:
            return token_file.readline().strip() or None
    except OSError:
        return None


class SamsungTVTizenConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for a Samsung TV."""

    VERSION = 1

    def __init__(self):
        """Initialize the flow."""
        self._host = None
        self._name = None
        self._title = None
        self._model = None
        self._mac = None
        self._port = DEFAULT_PORT
        self._token = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Return the options flow."""
        return SamsungTVTizenOptionsFlow()

    async def _async_load_device(self, host, raise_on_progress=True):
        """Read the TV description, set the unique ID and abort if already configured."""
        try:
            async with async_get_clientsession(self.hass).get(
                f"http://{host}:{INSECURE_PORT}/api/v2/",
                timeout=ClientTimeout(total=DEVICE_INFO_TIMEOUT),
            ) as response:
                info = await response.json(content_type=None)
            device = info.get("device") or {}
        except (ClientError, TimeoutError, ValueError, AttributeError) as ex:
            _LOGGER.debug("Samsung TV %s did not return device info: %s", host, ex)
            raise AbortFlow("cannot_connect") from ex

        udn = device.get("udn") or info.get("id")
        if device.get("type") != DEVICE_TYPE_TV or not udn:
            raise AbortFlow("not_supported")

        self._host = host
        self._name = (device.get("name") or DEVICE_TYPE_TV).replace("[TV] ", "")
        self._model = device.get("modelName")
        self._title = f"{self._name} ({self._model})" if self._model else self._name
        # Samsung sometimes returns "none" as the MAC address
        mac = device.get("wifiMac")
        self._mac = format_mac(mac) if mac and mac != "none" else None
        self._port = DEFAULT_PORT if device.get("TokenAuthSupport") == "true" else INSECURE_PORT

        await self.async_set_unique_id(udn.removeprefix("uuid:"), raise_on_progress=raise_on_progress)
        self._async_abort_if_configured()

    @callback
    def _async_abort_if_configured(self):
        """Keep the matching entry up to date with what was discovered and abort."""
        for entry in self._async_current_entries(include_ignore=False):
            # Entries imported while the TV was off don't have a unique ID yet
            if entry.unique_id != self.unique_id and (
                entry.unique_id is not None
                or (
                    entry.data[CONF_HOST] != self._host
                    and (not self._mac or entry.data.get(CONF_MAC) != self._mac)
                )
            ):
                continue
            data = {**entry.data, CONF_HOST: self._host}
            if not data.get(CONF_MAC) and self._mac:
                data[CONF_MAC] = self._mac
            changed = data != dict(entry.data)
            self.hass.config_entries.async_update_entry(entry, unique_id=self.unique_id, data=data)
            if changed:
                self.hass.config_entries.async_schedule_reload(entry.entry_id)
            raise AbortFlow("already_configured")
        self._abort_if_unique_id_configured()

    async def _async_step_discovered(self, host):
        """Handle a TV found by any of the discovery methods."""
        await self._async_load_device(host)
        self.context["title_placeholders"] = {"device": self._title}
        return await self.async_step_confirm()

    async def async_step_ssdp(self, discovery_info):
        """Handle a flow initialized by SSDP discovery."""
        host = urlparse(discovery_info.ssdp_location or "").hostname
        if not host:
            return self.async_abort(reason="cannot_connect")
        return await self._async_step_discovered(host)

    async def async_step_dhcp(self, discovery_info):
        """Handle a flow initialized by DHCP discovery."""
        return await self._async_step_discovered(discovery_info.ip)

    async def async_step_zeroconf(self, discovery_info):
        """Handle a flow initialized by zeroconf discovery."""
        return await self._async_step_discovered(discovery_info.host)

    async def async_step_user(self, user_input=None):
        """Handle a TV added by hand, for networks where discovery doesn't reach it."""
        errors = {}
        if user_input is not None:
            try:
                host = await self.hass.async_add_executor_job(
                    socket.gethostbyname, user_input[CONF_HOST]
                )
            except OSError:
                errors["base"] = "invalid_host"
            else:
                await self._async_load_device(host, raise_on_progress=False)
                self.context["title_placeholders"] = {"device": self._title}
                return await self.async_step_pairing({})

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_import(self, import_data):
        """Import a TV configured in YAML, keeping its name and with it the entity ID."""
        host = import_data[CONF_HOST]
        mac = format_mac(import_data[CONF_MAC]) if import_data.get(CONF_MAC) else None
        self._async_abort_entries_match({CONF_HOST: host})
        if mac:
            self._async_abort_entries_match({CONF_MAC: mac})

        try:
            await self._async_load_device(host, raise_on_progress=False)
        except AbortFlow as ex:
            # The TV may be off: discovery fills in the unique ID once it's back
            if ex.reason not in ("cannot_connect", "not_supported"):
                raise

        token = await self.hass.async_add_executor_job(_read_legacy_token, host)
        name = import_data[CONF_NAME]
        data = {
            CONF_HOST: host,
            CONF_NAME: name,
            CONF_PORT: import_data.get(CONF_PORT, DEFAULT_PORT),
            CONF_MAC: mac or self._mac,
            CONF_MODEL: self._model,
        }
        if token:
            data[CONF_TOKEN] = token
        return self.async_create_entry(
            title=name,
            data=data,
            options={key: import_data[key] for key in IMPORTED_OPTIONS if key in import_data},
        )

    async def async_step_confirm(self, user_input=None):
        """Ask the user to confirm a discovered TV."""
        if user_input is not None:
            return await self.async_step_pairing({})
        return self.async_show_form(
            step_id="confirm", description_placeholders={"device": self._title}
        )

    def _pair(self):
        """Connect to the TV, which asks the user to allow it. Return if it was allowed."""
        ws = SamsungTVWS(
            name=self._name,
            host=self._host,
            port=self._port,
            timeout=PAIRING_TIMEOUT,
            token=self._token,
        )
        try:
            ws.open()
        except (exceptions.ConnectionFailure, WebSocketException, OSError) as ex:
            _LOGGER.debug("Samsung TV %s did not pair: %s", self._host, ex)
            return False
        finally:
            ws.close()
        self._token = ws.token
        return True

    async def async_step_pairing(self, user_input=None):
        """Pair with the TV and save the token it returns."""
        errors = {}
        if user_input is not None:
            self._token = self._token or await self.hass.async_add_executor_job(
                _read_legacy_token, self._host
            )
            if await self.hass.async_add_executor_job(self._pair):
                data = {
                    CONF_HOST: self._host,
                    CONF_NAME: self._name,
                    CONF_PORT: self._port,
                    CONF_MAC: self._mac,
                    CONF_MODEL: self._model,
                }
                if self._token:
                    data[CONF_TOKEN] = self._token
                return self.async_create_entry(title=self._title, data=data)
            errors["base"] = "auth_missing"

        return self.async_show_form(
            step_id="pairing",
            description_placeholders={"device": self._title},
            data_schema=probatio.Schema({}),
            errors=errors,
        )


class SamsungTVTizenOptionsFlow(OptionsFlowWithReload):
    """Handle the options that used to be set in YAML."""

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        errors = {}
        if user_input is not None:
            for key in JSON_OPTIONS:
                if key not in user_input:
                    continue
                try:
                    if not isinstance(json.loads(user_input[key]), dict):
                        errors[key] = "invalid_json"
                except ValueError:
                    errors[key] = "invalid_json"
            if not errors:
                if CONF_TIMEOUT in user_input:
                    user_input[CONF_TIMEOUT] = int(user_input[CONF_TIMEOUT])
                return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                OPTIONS_SCHEMA, user_input or self.config_entry.options
            ),
            errors=errors,
        )
