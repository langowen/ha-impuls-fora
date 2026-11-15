import json
from pathlib import Path
from homeassistant.components.binary_sensor import BinarySensorEntity
from .entity import ForaEntity
from .const import DOMAIN

ALARMS = json.loads(Path(__file__).with_name("alarms.json").read_text())

async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ForaBinarySensor(coordinator, spec) for spec in ALARMS])

class ForaBinarySensor(ForaEntity, BinarySensorEntity):
    def __init__(self, coordinator, spec):
        self.address = spec["address"]
        super().__init__(coordinator, f"discrete_{self.address}", spec["name"])
        self.entity_id = f"binary_sensor.fora3330_d{self.address}"
        self._attr_extra_state_attributes = {"address": self.address, "function": 2}
        if self.address not in (15, 16, 17, 19, 21):
            self._attr_device_class = "problem"

    @property
    def is_on(self):
        return bool(self.coordinator.data["bits"][self.address])
