"""Typed values from the exported upsViewer register map."""
import json
from pathlib import Path
from homeassistant.components.sensor import SensorEntity
from .entity import ForaEntity
from .const import DOMAIN
from .protocol import decode

# Loaded during platform import (HA imports integrations in its import executor).
REGISTERS = json.loads(Path(__file__).with_name("registers.json").read_text())
UNITS = {"В": "V", "А": "A", "Гц": "Hz", "℃": "°C", "кВт": "kW",
         "кВА": "kVA", "кВАр": "kvar", "мин.": "min", "ч": "h", "День": "d", "%": "%"}
CLASSES = {"V": "voltage", "A": "current", "Hz": "frequency", "°C": "temperature",
           "kW": "power", "kVA": "apparent_power", "kvar": "reactive_power"}
STATES = {
    0: {450: "Нет нагрузки", 330: "Нормальный режим", 327: "Байпас"},
    1: {3: "Нет", 4: "Да"},
    2: {538: "Ожидание", 451: "Поддерживающий заряд", 331: "Ускоренный заряд", 326: "Разряд"},
}

async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ForaSensor(coordinator, spec) for spec in REGISTERS] +
                       [ForaCalculatedSensor(coordinator, key, *spec) for key, spec in CALCULATED.items()
                        if not key.startswith("generator_") or (
                            entry.options.get("generator_enabled", False) and entry.options.get("generator_contactor"))])

class ForaSensor(ForaEntity, SensorEntity):
    def __init__(self, coordinator, spec):
        self.spec = spec
        address = spec["address"]
        super().__init__(coordinator, f"register_{address}", spec["name"])
        # Stable English IDs make the supplied dashboard independent of UI language.
        self.entity_id = f"sensor.fora3330_r{address}"
        self._attr_extra_state_attributes = {"register": address, "function": 4,
            "data_type": spec["dtype"], "scale": spec["scale"]}
        if address not in STATES:
            unit = UNITS.get(spec["unit"])
            self._attr_native_unit_of_measurement = unit
            self._attr_device_class = "battery" if address == 101 else CLASSES.get(unit)
            self._attr_state_class = "measurement"
            self._attr_suggested_display_precision = 2 if spec["scale"] == 0.01 else (1 if spec["scale"] == 0.1 else 0)

    @property
    def native_value(self):
        raw = self.coordinator.data["registers"][self.spec["address"]]
        if self.spec["address"] in STATES:
            return STATES[self.spec["address"]].get(raw, f"Неизвестный код {raw}")
        return decode(raw, self.spec["dtype"], self.spec["scale"])


CALCULATED = {
    "output_power": ("Суммарная выходная мощность", "W", "power"),
    "battery_power": ("Мощность АКБ", "W", "power"),
    "charge_power": ("Мощность заряда АКБ", "W", "power"),
    "discharge_power": ("Мощность разряда АКБ", "W", "power"),
    "charge_energy": ("Энергия заряда АКБ", "kWh", "energy"),
    "discharge_energy": ("Энергия разряда АКБ", "kWh", "energy"),
    "generator_power": ("Мощность генератора (расчётная)", "W", "power"),
    "generator_energy": ("Выработка генератора (расчётная)", "kWh", "energy"),
}

class ForaCalculatedSensor(ForaEntity, SensorEntity):
    def __init__(self, coordinator, key, name, unit, device_class):
        super().__init__(coordinator, key, name)
        self.key = key
        self.entity_id = f"sensor.fora3330_{key}"
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_state_class = "total" if device_class == "energy" else "measurement"
        self._attr_suggested_display_precision = 4 if device_class == "energy" else 1
        self._attr_extra_state_attributes = {"calculated": True}
        if key.startswith("generator_"):
            self._attr_extra_state_attributes.update(
                measurement_side="ups_ac_input", method="sum_phase_voltage_current_pf",
                source_entity=coordinator.entry.options.get("generator_contactor"),
                include_bypass=coordinator.entry.options.get("generator_include_bypass", False))
        elif key != "output_power":
            self._attr_extra_state_attributes.update(
                measurement_side="battery_dc",
                direction_mode=coordinator.entry.options.get("battery_mode", "disabled"),
                channels=coordinator.entry.options.get("battery_channels", "both"))

    @property
    def available(self):
        return super().available and self.key in self.coordinator.data.get("calculated", {})

    @property
    def native_value(self):
        return self.coordinator.data.get("calculated", {}).get(self.key)
