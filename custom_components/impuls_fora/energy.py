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

    def __init__(self, max_gap, totals=None, keys=("charge_energy", "discharge_energy")):
        self.max_gap = max_gap
        self.totals = dict.fromkeys(keys, 0.0)
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
        if len(power) != len(self.totals) or any(not isfinite(p) or p < 0 for p in power):
            raise ValueError("Invalid battery power")
        if self.previous is not None:
            timestamp, old_power = self.previous
            seconds = now - timestamp
            if 0 < seconds <= self.max_gap:
                for key, watts in zip(self.totals, old_power):
                    self.totals[key] += watts * seconds / 3_600_000
        self.previous = now, power


def generator_power(registers, source_state, include_bypass=False):
    """Estimate active AC input watts only while ATS feeds load from generator.

    Requires all generator loads to be downstream of this UPS. Voltages are
    phase-to-neutral; input currents, and optionally bypass currents, must
    represent distinct branches. U*I*PF is an estimate, not an energy meter.
    """
    if source_state in ("mains", "off"):
        return 0.0
    if source_state != "generator":
        return None
    groups = [(57, 60, 66)]
    if include_bypass:
        groups.append((44, 47, 53))
    watts = 0.0
    for voltage, current, pf in groups:
        for phase in range(3):
            values = [registers[base + phase] for base in (voltage, current, pf)]
            if 65535 in values:
                return None
            v, i, factor = values[0] * 0.1, values[1] * 0.1, values[2] * 0.01
            if not 0 <= factor <= 1 or (v == 0 and i != 0):
                return None
            watts += v * i * factor
    return round(watts, 6)
