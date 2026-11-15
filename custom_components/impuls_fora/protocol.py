"""Read-only Modbus adapter. No Home Assistant imports."""
import asyncio
import inspect

class ReadError(Exception):
    """Invalid, short or failed Modbus response."""

def decode(raw, dtype, scale):
    if not 0 <= raw <= 65535:
        raise ReadError("Invalid 16-bit value")
    if dtype == "int16" and raw >= 32768:
        raw -= 65536
    return round(raw * scale, 6)

class Reader:
    def __init__(self, client, unit):
        self.client = client
        self.unit = unit
        self.lock = asyncio.Lock()

    async def _read(self, method, start, count, field):
        # HA owns the pymodbus dependency; support its old and new unit keywords.
        params = inspect.signature(method).parameters
        key = "device_id" if "device_id" in params else "slave"
        result = await method(address=start, count=count, **{key: self.unit})
        if result.isError():
            raise ReadError(f"Modbus error at {start}: {result}")
        values = getattr(result, field, None)
        if values is None or len(values) < count:
            raise ReadError(f"Short response at {start}")
        return values[:count]

    async def snapshot(self):
        async with self.lock:
            if not self.client.connected and not await self.client.connect():
                raise ReadError("Cannot connect to UPS")
            registers = {}
            # Separate supported blocks; never request undefined registers 3..43.
            for start, count in ((0, 3), (44, 63)):
                values = await self._read(self.client.read_input_registers,
                                          start, count, "registers")
                registers.update(enumerate(values, start))
                await asyncio.sleep(0.1)
            bits = await self._read(self.client.read_discrete_inputs, 0, 23, "bits")
            return {"registers": registers, "bits": dict(enumerate(bits))}
