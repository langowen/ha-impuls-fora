"""One serialized, shared polling cycle for the entire device."""
from datetime import timedelta
import logging
from time import monotonic
from pymodbus.client import AsyncModbusTcpClient
from pymodbus.exceptions import ModbusException
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.storage import Store
from .const import DOMAIN
from .protocol import Reader, ReadError
from .energy import EnergyCounter, battery_power, generator_power

class ForaCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry):
        self.entry = entry
        self._hass = hass
        self.client = AsyncModbusTcpClient(entry.data["host"],
            port=entry.data["port"], timeout=5, retries=1)
        self.reader = Reader(self.client, entry.data["unit_id"])
        self.energy = EnergyCounter(entry.data["scan_interval"] * 2.5)
        self.energy_store = Store(hass, 1, f"{DOMAIN}_energy_{entry.entry_id}")
        self.generation = EnergyCounter(entry.data["scan_interval"] * 2.5, keys=("generator_energy",))
        self.generation_store = Store(hass, 1, f"{DOMAIN}_generation_{entry.entry_id}")
        super().__init__(hass, logging.getLogger(__name__), name=DOMAIN,
            update_interval=timedelta(seconds=entry.data["scan_interval"]),
            config_entry=entry)

    async def async_load_energy(self):
        stored = await self.energy_store.async_load()
        if stored is not None:
            # Fail setup rather than resetting damaged counters and statistics.
            self.energy = EnergyCounter(self.entry.data["scan_interval"] * 2.5, stored)
        generated = await self.generation_store.async_load()
        if generated is not None:
            self.generation = EnergyCounter(self.entry.data["scan_interval"] * 2.5,
                                            generated, keys=("generator_energy",))

    async def _async_update_data(self):
        try:
            snapshot = await self.reader.snapshot()
        except (ReadError, ModbusException, OSError, TimeoutError) as exc:
            self.energy.break_interval()
            self.generation.break_interval()
            self.client.close()
            raise UpdateFailed(f"UPS read failed: {exc}") from exc
        power = battery_power(snapshot["registers"],
            self.entry.options.get("battery_mode", "disabled"),
            self.entry.options.get("battery_channels", "both"))
        now = monotonic()
        self.energy.update(now, power)
        calculated = {"output_power": round(sum(snapshot["registers"][a] for a in (88, 89, 90)) * 100, 6)}
        if power is not None:
            calculated.update(charge_power=round(power[0], 6), discharge_power=round(power[1], 6),
                              battery_power=round(power[1] - power[0], 6), **self.energy.totals)
            # Persist before publishing, including each counter increment. Do not
            # bridge downtime or let a crash restore an already published lower total.
            try:
                await self.energy_store.async_save(dict(self.energy.totals))
            except OSError as exc:
                self.energy.break_interval()
                self.generation.break_interval()
                raise UpdateFailed(f"Cannot persist battery energy: {exc}") from exc
        entity_id = (self.entry.options.get("generator_contactor")
                     if self.entry.options.get("generator_enabled", False) else None)
        source = self._hass.states.get(entity_id) if entity_id else None
        include_bypass = self.entry.options.get("generator_include_bypass", False)
        gen_power = generator_power(snapshot["registers"], source.state if source else None, include_bypass)
        if source and source.state == "generator" and snapshot["bits"].get(16) and not include_bypass:
            gen_power = None  # Do not present rectifier-only power as full generation on bypass.
        self.generation.update(now, (gen_power,) if gen_power is not None else None)
        if gen_power is not None:
            calculated.update(generator_power=gen_power, **self.generation.totals)
            try:
                await self.generation_store.async_save(dict(self.generation.totals))
            except OSError as exc:
                self.generation.break_interval()
                self.energy.break_interval()
                raise UpdateFailed(f"Cannot persist generator energy: {exc}") from exc
        snapshot["calculated"] = calculated
        return snapshot
