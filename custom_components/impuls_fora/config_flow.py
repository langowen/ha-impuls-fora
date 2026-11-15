"""UI setup and connection validation."""
import logging
import voluptuous as vol
from pymodbus.client import AsyncModbusTcpClient
from pymodbus.exceptions import ModbusException
from homeassistant import config_entries
from .const import DOMAIN, DEFAULT_HOST, DEFAULT_PORT, DEFAULT_UNIT, DEFAULT_INTERVAL
from .protocol import Reader, ReadError

_LOGGER = logging.getLogger(__name__)

class ForaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

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
