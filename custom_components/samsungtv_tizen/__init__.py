"""The samsungtv component."""
from homeassistant.const import Platform

PLATFORMS = [Platform.MEDIA_PLAYER]


async def async_setup_entry(hass, entry):
    """Set up the Samsung TV from a config entry."""
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass, entry):
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
