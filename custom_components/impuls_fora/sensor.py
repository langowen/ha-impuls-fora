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
    async_add_entities([ForaSensor(coordinator, spec) for spec in REGISTERS])

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
