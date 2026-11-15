"""Pure calculations for estimated battery DC energy; no device writes."""
from math import isfinite
from .protocol import decode

MODES = ("disabled", "status", "positive_charge", "positive_discharge")
CHANNELS = ("both", "positive", "negative")

def battery_power(registers, mode="disabled", channels="both"):
    """Return charge/discharge watts, or None when direction is unconfigured.

    Both channels means two independent DC battery branches: sum V+*I+ and V-*I-.
    Do not multiply the sum of voltages by the sum of currents.
    """
    if mode not in MODES or channels not in CHANNELS:
        raise ValueError("Invalid battery energy configuration")
    if mode == "disabled":
        return None
    pairs = {"positive": ((97, 99),), "negative": ((98, 100),),
             "both": ((97, 99), (98, 100))}[channels]
    powers = []
    for voltage, current in pairs:
        # 0xffff in unsigned voltage is treated as missing, never as 6553.5 V.
        if registers[voltage] == 0xFFFF:
            return None
        v = decode(registers[voltage], "uint16", 0.1)
        i = decode(registers[current], "int16", 0.1)
        if v == 0 and i != 0:
            return None
        powers.append(v * i)
    if mode == "status":
        magnitude = sum(abs(p) for p in powers)
        state = registers[2]
        if state == 326:  # Documented battery discharging state.
            return 0.0, magnitude
        if state in (451, 331):  # Float / boost charging.
            return magnitude, 0.0
        if state == 538 and magnitude == 0:
            return 0.0, 0.0
        return None  # An unknown state must not silently become zero.
    sign = 1 if mode == "positive_charge" else -1
    return (sum(max(sign * p, 0) for p in powers),
            sum(max(-sign * p, 0) for p in powers))

class EnergyCounter:
    """Left integration of watts to kWh, with gaps explicitly excluded."""

    def __init__(self, max_gap, totals=None):
        self.max_gap = max_gap
        self.totals = {"charge_energy": 0.0, "discharge_energy": 0.0}
        if totals is not None:
            for key in self.totals:
                value = totals[key]
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value < 0:
                    raise ValueError("Invalid persisted energy counter")
                self.totals[key] = value
        self.previous = None

    def break_interval(self):
        self.previous = None

    def update(self, now, power):
        if power is None:
            self.break_interval()
            return
        if any(not isfinite(p) or p < 0 for p in power):
            raise ValueError("Invalid battery power")
        if self.previous is not None:
            timestamp, old_power = self.previous
            seconds = now - timestamp
            if 0 < seconds <= self.max_gap:
                for key, watts in zip(self.totals, old_power):
                    self.totals[key] += watts * seconds / 3_600_000
        self.previous = now, power
