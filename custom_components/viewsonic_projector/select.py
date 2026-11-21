"""Select entities for the ViewSonic Projector integration."""

from collections.abc import Mapping
from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import LOGGER
from .coordinator import ViewSonicConfigEntry, ViewSonicCoordinator
from .entity import ViewSonicQueryEntity
from .protocol import (
    ASPECT_RATIOS,
    AUDIO_MODES,
    COLOR_MODES,
    COLOR_TEMPERATURES,
    EOTF_LEVELS,
    FRAME_INTERPOLATION_LEVELS,
    GAMMAS,
    HDMI_FORMATS,
    HDMI_RANGES,
    HDR_MODES,
    LANGUAGES,
    LIGHT_SOURCE_MODES,
    PRIMARY_COLORS,
    PROJECTOR_POSITIONS,
    QUERIES,
    REMOTE_CONTROL_CODES,
    SCREEN_COLORS,
    SPLASH_SCREENS,
    THREE_D_SYNC_MODES,
    Query,
)

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class ViewSonicSelectEntityDescription(SelectEntityDescription):
    """Describes a projector setting with a fixed set of values."""

    query: Query
    values: Mapping[str, int]


SELECTS: tuple[ViewSonicSelectEntityDescription, ...] = (
    ViewSonicSelectEntityDescription(
        key="color_mode",
        translation_key="color_mode",
        query=Query.COLOR_MODE,
        values=COLOR_MODES,
    ),
    ViewSonicSelectEntityDescription(
        key="light_source_mode",
        translation_key="light_source_mode",
        query=Query.LIGHT_SOURCE_MODE,
        values=LIGHT_SOURCE_MODES,
    ),
    ViewSonicSelectEntityDescription(
        key="aspect_ratio",
        translation_key="aspect_ratio",
        query=Query.ASPECT_RATIO,
        values=ASPECT_RATIOS,
    ),
    ViewSonicSelectEntityDescription(
        key="color_temperature",
        translation_key="color_temperature",
        query=Query.COLOR_TEMPERATURE,
        values=COLOR_TEMPERATURES,
    ),
    ViewSonicSelectEntityDescription(
        key="projector_position",
        translation_key="projector_position",
        query=Query.PROJECTOR_POSITION,
        values=PROJECTOR_POSITIONS,
        entity_category=EntityCategory.CONFIG,
    ),
    ViewSonicSelectEntityDescription(
        key="gamma",
        translation_key="gamma",
        query=Query.GAMMA,
        values=GAMMAS,
        entity_registry_enabled_default=False,
    ),
    ViewSonicSelectEntityDescription(
        key="hdr",
        translation_key="hdr",
        query=Query.HDR,
        values=HDR_MODES,
        entity_registry_enabled_default=False,
    ),
    ViewSonicSelectEntityDescription(
        key="eotf",
        translation_key="eotf",
        query=Query.EOTF,
        values=EOTF_LEVELS,
        entity_registry_enabled_default=False,
    ),
    ViewSonicSelectEntityDescription(
        key="frame_interpolation",
        translation_key="frame_interpolation",
        query=Query.FRAME_INTERPOLATION,
        values=FRAME_INTERPOLATION_LEVELS,
        entity_registry_enabled_default=False,
    ),
    ViewSonicSelectEntityDescription(
        key="audio_mode",
        translation_key="audio_mode",
        query=Query.AUDIO_MODE,
        values=AUDIO_MODES,
        entity_registry_enabled_default=False,
    ),
    ViewSonicSelectEntityDescription(
        key="three_d_sync",
        translation_key="three_d_sync",
        query=Query.THREE_D_SYNC,
        values=THREE_D_SYNC_MODES,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    ),
    ViewSonicSelectEntityDescription(
        key="hdmi_format",
        translation_key="hdmi_format",
        query=Query.HDMI_FORMAT,
        values=HDMI_FORMATS,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    ),
    ViewSonicSelectEntityDescription(
        key="hdmi_range",
        translation_key="hdmi_range",
        query=Query.HDMI_RANGE,
        values=HDMI_RANGES,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    ),
    ViewSonicSelectEntityDescription(
        key="primary_color",
        translation_key="primary_color",
        query=Query.PRIMARY_COLOR,
        values=PRIMARY_COLORS,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    ),
    ViewSonicSelectEntityDescription(
        key="splash_screen",
        translation_key="splash_screen",
        query=Query.SPLASH_SCREEN,
        values=SPLASH_SCREENS,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    ),
    ViewSonicSelectEntityDescription(
        key="screen_color",
        translation_key="screen_color",
        query=Query.SCREEN_COLOR,
        values=SCREEN_COLORS,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    ),
    ViewSonicSelectEntityDescription(
        key="language",
        translation_key="language",
        query=Query.LANGUAGE,
        values=LANGUAGES,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    ),
    ViewSonicSelectEntityDescription(
        key="remote_control_code",
        translation_key="remote_control_code",
        query=Query.REMOTE_CONTROL_CODE,
        values=REMOTE_CONTROL_CODES,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ViewSonicConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the projector selects."""
    coordinator = entry.runtime_data
    async_add_entities(
        ViewSonicSelect(coordinator, description) for description in SELECTS
    )


class ViewSonicSelect(ViewSonicQueryEntity, SelectEntity):
    """A projector setting with a fixed set of values."""

    entity_description: ViewSonicSelectEntityDescription

    def __init__(
        self,
        coordinator: ViewSonicCoordinator,
        description: ViewSonicSelectEntityDescription,
    ) -> None:
        """Initialize the select."""
        super().__init__(coordinator, description, description.query)
        self._attr_options = list(
            coordinator.profile.options.get(description.key, description.values)
        )
        self._by_value = {value: name for name, value in description.values.items()}
        self._unknown_logged: set[int] = set()

    @property
    def current_option(self) -> str | None:
        """Return the current option."""
        value = self.raw_value
        if value is None:
            return None
        option = self._by_value.get(value)
        if option is None and value not in self._unknown_logged:
            self._unknown_logged.add(value)
            LOGGER.info(
                "%s reported undocumented value 0x%02X for %s",
                self.coordinator.device_info.get("name"),
                value,
                self.entity_description.key,
            )
        return option

    async def async_select_option(self, option: str) -> None:
        """Change the setting."""
        await self.coordinator.async_write(
            QUERIES[self._query].code,
            self.entity_description.values[option],
            refresh=self._query,
        )
