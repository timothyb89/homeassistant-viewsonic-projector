"""Remote entity for the ViewSonic Projector integration.

Emulates the projector's IR remote: use ``remote.send_command`` with any of
the commands in ``REMOTE_COMMANDS`` (e.g. ``menu``, ``up``, ``enter``).
"""

import asyncio
from collections.abc import Iterable
from typing import Any

from homeassistant.components.remote import (
    ATTR_DELAY_SECS,
    ATTR_NUM_REPEATS,
    DEFAULT_DELAY_SECS,
    RemoteEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import ViewSonicConfigEntry, ViewSonicCoordinator
from .entity import ViewSonicEntity
from .protocol import (
    ASPECT_RATIO_CYCLE,
    AUDIO_MODE_CYCLE,
    COLOR_MODE_CYCLE,
    HOME,
    LENS_FOCUS,
    LIGHT_SOURCE_MODE_CYCLE,
    POWER_TOGGLE,
    REMOTE_KEY,
    REMOTE_KEYS,
    VOLUME_DOWN,
    VOLUME_UP,
    Code,
    PowerState,
)

PARALLEL_UPDATES = 1

REMOTE_COMMANDS: dict[str, tuple[Code, int]] = {
    **{name: (REMOTE_KEY, key) for name, key in REMOTE_KEYS.items()},
    "home": (HOME, 0),
    "focus_near": (LENS_FOCUS, 0),
    "focus_far": (LENS_FOCUS, 1),
    "volume_up": (VOLUME_UP, 0),
    "volume_down": (VOLUME_DOWN, 0),
    "aspect_ratio": (ASPECT_RATIO_CYCLE, 0),
    "color_mode": (COLOR_MODE_CYCLE, 0),
    "light_source_mode": (LIGHT_SOURCE_MODE_CYCLE, 0),
    "audio_mode": (AUDIO_MODE_CYCLE, 0),
    "power": (POWER_TOGGLE, 0),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ViewSonicConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the projector remote."""
    async_add_entities([ViewSonicRemote(entry.runtime_data)])


class ViewSonicRemote(ViewSonicEntity, RemoteEntity):
    """Sends remote control key presses."""

    _attr_translation_key = "remote"

    def __init__(self, coordinator: ViewSonicCoordinator) -> None:
        """Initialize the remote."""
        super().__init__(coordinator, "remote")

    @property
    def is_on(self) -> bool | None:
        """Return whether the projector is on."""
        state = self.coordinator.power_state
        if state is None:
            return None
        return state in (PowerState.ON, PowerState.WARMING_UP)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the projector on."""
        await self.coordinator.async_turn_on()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the projector off."""
        await self.coordinator.async_turn_off()

    async def async_send_command(self, command: Iterable[str], **kwargs: Any) -> None:
        """Send one or more remote commands."""
        commands = list(command)
        if unknown := [name for name in commands if name not in REMOTE_COMMANDS]:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_remote_command",
                translation_placeholders={
                    "command": ", ".join(unknown),
                    "commands": ", ".join(REMOTE_COMMANDS),
                },
            )
        repeats: int = kwargs.get(ATTR_NUM_REPEATS, 1)
        delay: float = kwargs.get(ATTR_DELAY_SECS, DEFAULT_DELAY_SECS)
        first = True
        for _ in range(repeats):
            for name in commands:
                if not first:
                    await asyncio.sleep(delay)
                first = False
                code, data = REMOTE_COMMANDS[name]
                await self.coordinator.async_write(
                    code, data, require_on=name != "power"
                )
        # Remote keys can change any setting; refresh everything soon.
        await self.coordinator.async_request_settings_refresh()
