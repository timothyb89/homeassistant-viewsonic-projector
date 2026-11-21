"""Media player entity for the ViewSonic Projector integration."""

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_SOURCES, DOMAIN
from .coordinator import ViewSonicConfigEntry, ViewSonicCoordinator
from .entity import ViewSonicEntity
from .protocol import (
    INPUT_SOURCES,
    QUERIES,
    VOLUME_DOWN,
    VOLUME_SET,
    VOLUME_UP,
    PowerState,
    Query,
)

PARALLEL_UPDATES = 1

_SOURCE_BY_VALUE = {value: name for name, value in INPUT_SOURCES.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ViewSonicConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the projector media player."""
    async_add_entities([ViewSonicMediaPlayer(entry.runtime_data)])


class ViewSonicMediaPlayer(ViewSonicEntity, MediaPlayerEntity):
    """Power, input, volume and mute control."""

    _attr_name = None
    _attr_translation_key = "projector"
    _attr_device_class = MediaPlayerDeviceClass.TV
    _attr_supported_features = (
        MediaPlayerEntityFeature.TURN_ON
        | MediaPlayerEntityFeature.TURN_OFF
        | MediaPlayerEntityFeature.SELECT_SOURCE
        | MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.VOLUME_STEP
        | MediaPlayerEntityFeature.VOLUME_MUTE
    )

    def __init__(self, coordinator: ViewSonicCoordinator) -> None:
        """Initialize the media player."""
        super().__init__(
            coordinator,
            "projector",
            frozenset({Query.INPUT_SOURCE, Query.VOLUME, Query.MUTE}),
        )
        self._volume_max = coordinator.profile.volume_max
        self._attr_volume_step = 1 / self._volume_max
        self._attr_source_list = list(
            coordinator.config_entry.options.get(
                CONF_SOURCES, coordinator.profile.sources
            )
        )

    @property
    def state(self) -> MediaPlayerState | None:
        """Return the power state."""
        match self.coordinator.power_state:
            case PowerState.ON | PowerState.WARMING_UP:
                return MediaPlayerState.ON
            case PowerState.OFF | PowerState.COOLING_DOWN:
                return MediaPlayerState.OFF
        return None

    @property
    def source(self) -> str | None:
        """Return the current input source."""
        if not self.coordinator.is_on:
            return None
        value = self.coordinator.value(Query.INPUT_SOURCE)
        return None if value is None else _SOURCE_BY_VALUE.get(value)

    @property
    def volume_level(self) -> float | None:
        """Return the volume level (0..1)."""
        if not self.coordinator.is_on:
            return None
        value = self.coordinator.value(Query.VOLUME)
        if value is None:
            return None
        return min(max(value / self._volume_max, 0.0), 1.0)

    @property
    def is_volume_muted(self) -> bool | None:
        """Return whether audio is muted."""
        if not self.coordinator.is_on:
            return None
        value = self.coordinator.value(Query.MUTE)
        return None if value is None else bool(value)

    async def async_turn_on(self) -> None:
        """Turn the projector on."""
        await self.coordinator.async_turn_on()

    async def async_turn_off(self) -> None:
        """Turn the projector off."""
        await self.coordinator.async_turn_off()

    async def async_select_source(self, source: str) -> None:
        """Select an input source."""
        if source not in INPUT_SOURCES:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_source",
                translation_placeholders={"source": source},
            )
        await self.coordinator.async_write(
            QUERIES[Query.INPUT_SOURCE].code,
            INPUT_SOURCES[source],
            refresh=Query.INPUT_SOURCE,
        )

    async def async_set_volume_level(self, volume: float) -> None:
        """Set the volume level (0..1)."""
        await self.coordinator.async_write(
            VOLUME_SET, round(volume * self._volume_max), refresh=Query.VOLUME
        )

    async def async_volume_up(self) -> None:
        """Increase the volume by one step."""
        await self.coordinator.async_write(
            VOLUME_UP, refresh=(Query.VOLUME, Query.MUTE)
        )

    async def async_volume_down(self) -> None:
        """Decrease the volume by one step."""
        await self.coordinator.async_write(
            VOLUME_DOWN, refresh=(Query.VOLUME, Query.MUTE)
        )

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute or unmute audio."""
        await self.coordinator.async_write(
            QUERIES[Query.MUTE].code, 1 if mute else 0, refresh=Query.MUTE
        )
