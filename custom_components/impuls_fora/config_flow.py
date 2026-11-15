"""UI setup and connection validation."""
import logging
import voluptuous as vol
from pymodbus.client import AsyncModbusTcpClient
from pymodbus.exceptions import ModbusException
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
from .const import DOMAIN, DEFAULT_HOST, DEFAULT_PORT, DEFAULT_UNIT, DEFAULT_INTERVAL
from .protocol import Reader, ReadError

_LOGGER = logging.getLogger(__name__)

class ForaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return ForaOptionsFlow()

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            user_input["host"] = user_input["host"].strip().lower()
            await self.async_set_unique_id(
                f'{user_input["host"]}:{user_input["port"]}:{user_input["unit_id"]}')
            self._abort_if_unique_id_configured()
            client = AsyncModbusTcpClient(user_input["host"],
                port=user_input["port"], timeout=5, retries=0)
            try:
                await Reader(client, user_input["unit_id"]).snapshot()
            except (ReadError, ModbusException, OSError, TimeoutError):
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected UPS setup error")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(title="Импульс ФОРА 3330", data=user_input)
            finally:
                client.close()
        defaults = user_input or {}
        schema = vol.Schema({
            vol.Required("host", default=defaults.get("host", DEFAULT_HOST)): str,
            vol.Required("port", default=defaults.get("port", DEFAULT_PORT)):
                vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
            vol.Required("unit_id", default=defaults.get("unit_id", DEFAULT_UNIT)):
                vol.All(vol.Coerce(int), vol.Range(min=1, max=247)),
            vol.Required("scan_interval", default=defaults.get("scan_interval", DEFAULT_INTERVAL)):
                vol.All(vol.Coerce(int), vol.Range(min=5, max=300)),
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)


class ForaOptionsFlow(config_entries.OptionsFlow):
    """Configure direction and branch topology without replacing the device."""

    async def async_step_init(self, user_input=None):
        errors = {}
        if user_input is not None:
            if user_input.get("generator_enabled") and not user_input.get("generator_contactor"):
                errors["base"] = "generator_source_required"
            else:
                return self.async_create_entry(title="", data=user_input)
        options = user_input if user_input is not None else self.config_entry.options
        return self.async_show_form(step_id="init", errors=errors, data_schema=vol.Schema({
            vol.Required("battery_mode", default=options.get("battery_mode", "disabled")):
                vol.In({"disabled": "Отключено — до проверки каналов АКБ",
                        "status": "Направление по состоянию АКБ (326/451/331)",
                        "positive_charge": "Положительный ток — заряд",
                        "positive_discharge": "Положительный ток — разряд"}),
            vol.Required("battery_channels", default=options.get("battery_channels", "both")):
                vol.In({"both": "Две независимые ветви АКБ: + и −",
                        "positive": "Только канал АКБ +",
                        "negative": "Только канал АКБ −"}),
            vol.Required("generator_enabled", default=options.get("generator_enabled", False)): bool,
            vol.Optional("generator_contactor", description={"suggested_value": options.get("generator_contactor", "")}):
                selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
            vol.Required("generator_include_bypass", default=options.get("generator_include_bypass", False)): bool,
        }))
