"""One serialized, shared polling cycle for the entire device."""
from datetime import timedelta
import logging
from pymodbus.client import AsyncModbusTcpClient
from pymodbus.exceptions import ModbusException
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from .const import DOMAIN
from .protocol import Reader, ReadError

class ForaCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry):
        self.entry = entry
        self.client = AsyncModbusTcpClient(entry.data["host"],
            port=entry.data["port"], timeout=5, retries=1)
        self.reader = Reader(self.client, entry.data["unit_id"])
        super().__init__(hass, logging.getLogger(__name__), name=DOMAIN,
            update_interval=timedelta(seconds=entry.data["scan_interval"]),
            config_entry=entry)

    async def _async_update_data(self):
        try:
            return await self.reader.snapshot()
        except (ReadError, ModbusException, OSError, TimeoutError) as exc:
            self.client.close()
            raise UpdateFailed(f"UPS read failed: {exc}") from exc
