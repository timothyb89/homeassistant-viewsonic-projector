"""Button entities for the ViewSonic Projector integration."""

from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ViewSonicConfigEntry, ViewSonicCoordinator
from .entity import ViewSonicEntity
from .protocol import (
    AUTO_ADJUST,
    RESET_ALL_SETTINGS,
    RESET_COLOR_SETTINGS,
    RESET_LIGHT_SOURCE_HOURS,
    Code,
    Query,
)

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class ViewSonicButtonEntityDescription(ButtonEntityDescription):
    """Describes a one-shot projector command."""

    code: Code
    # Values that change as a result and should be read back.
    refresh: tuple[Query, ...] = ()


BUTTONS: tuple[ViewSonicButtonEntityDescription, ...] = (
    ViewSonicButtonEntityDescription(
        key="auto_adjust",
        translation_key="auto_adjust",
        code=AUTO_ADJUST,
        entity_registry_enabled_default=False,
    ),
    ViewSonicButtonEntityDescription(
        key="reset_color_settings",
        translation_key="reset_color_settings",
        code=RESET_COLOR_SETTINGS,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    ),
    ViewSonicButtonEntityDescription(
        key="reset_all_settings",
        translation_key="reset_all_settings",
        code=RESET_ALL_SETTINGS,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    ),
    ViewSonicButtonEntityDescription(
        key="reset_light_source_hours",
        translation_key="reset_light_source_hours",
        code=RESET_LIGHT_SOURCE_HOURS,
        refresh=(Query.LIGHT_SOURCE_HOURS, Query.EQUIVALENT_LIGHT_SOURCE_HOURS),
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ViewSonicConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the projector buttons."""
    coordinator = entry.runtime_data
    async_add_entities(
        ViewSonicButton(coordinator, description) for description in BUTTONS
    )


class ViewSonicButton(ViewSonicEntity, ButtonEntity):
    """A one-shot projector command."""

    entity_description: ViewSonicButtonEntityDescription

    def __init__(
        self,
        coordinator: ViewSonicCoordinator,
        description: ViewSonicButtonEntityDescription,
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    async def async_press(self) -> None:
        """Send the command."""
        await self.coordinator.async_write(
            self.entity_description.code,
            refresh=self.entity_description.refresh or None,
        )
