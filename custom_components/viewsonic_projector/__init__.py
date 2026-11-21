"""The ViewSonic Projector integration."""

from homeassistant.const import CONF_DEVICE, Platform
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .client import ViewSonicProjector
from .const import CONF_BAUD_RATE, DOMAIN
from .coordinator import ViewSonicConfigEntry, ViewSonicCoordinator
from .services import async_setup_services

PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.MEDIA_PLAYER,
    Platform.NUMBER,
    Platform.REMOTE,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the ViewSonic Projector actions."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ViewSonicConfigEntry) -> None:
    """Set up a ViewSonic projector from a config entry."""
    client = ViewSonicProjector(entry.data[CONF_DEVICE], entry.data[CONF_BAUD_RATE])
    coordinator = ViewSonicCoordinator(hass, entry, client)
    try:
        await coordinator.async_config_entry_first_refresh()
    except BaseException:
        # Release the serial port so a retry (or another integration) can use it.
        await client.disconnect()
        raise

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # The first refresh only read the power state; now that the entities have
    # subscribed, read the settings they need.
    entry.async_create_background_task(
        hass,
        coordinator.async_request_settings_refresh(),
        f"{DOMAIN} initial settings refresh",
    )


async def async_unload_entry(hass: HomeAssistant, entry: ViewSonicConfigEntry) -> None:
    """Unload a config entry; the coordinator closes the port on shutdown."""
    await hass.config_entries.async_unload_platforms_or_raise(entry, PLATFORMS)
