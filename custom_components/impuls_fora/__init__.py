"""Импульс ФОРА: local read-only Modbus TCP integration."""
from homeassistant.const import Platform
from .const import DOMAIN
from .coordinator import ForaCoordinator

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]

async def async_setup_entry(hass, entry):
    coordinator = ForaCoordinator(hass, entry)
    try:
        await coordinator.async_load_energy()
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        coordinator.client.close()
        raise
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        coordinator.client.close()
        hass.data[DOMAIN].pop(entry.entry_id, None)
        raise
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True

async def async_reload_entry(hass, entry):
    await hass.config_entries.async_reload(entry.entry_id)

async def async_unload_entry(hass, entry):
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        coordinator.client.close()
        return True
    return False
