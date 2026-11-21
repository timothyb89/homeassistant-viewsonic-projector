"""Number entities for the ViewSonic Projector integration.

Most picture adjustments can only be nudged with increase/decrease commands;
setting such a value steps it towards the target and reads it back. Values that
the projector accepts directly (BrilliantColor, overscan) are written as is.
"""

from dataclasses import dataclass

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ViewSonicConfigEntry, ViewSonicCoordinator
from .entity import ViewSonicQueryEntity
from .protocol import QUERIES, RGB_GAIN, RGB_OFFSET, Code, Query

PARALLEL_UPDATES = 1

# Range used when a model profile does not define one; deliberately wide since
# models differ (e.g. 0..100 or -50..50). The projector stops at its own limit.
_WIDE_RANGE = (-100.0, 100.0)


@dataclass(frozen=True, kw_only=True)
class ViewSonicNumberEntityDescription(NumberEntityDescription):
    """Describes a numeric projector setting."""

    query: Query
    # True: write the value directly to the query's address.
    # False: step with increase/decrease commands at ``step_code``.
    direct: bool = False
    step_code: Code | None = None
    step_prefix: bytes = b""
    native_min_value: float = _WIDE_RANGE[0]
    native_max_value: float = _WIDE_RANGE[1]
    native_step: float = 1


def _rgb(
    key: str, query: Query, code: Code, channel: int
) -> ViewSonicNumberEntityDescription:
    return ViewSonicNumberEntityDescription(
        key=key,
        translation_key=key,
        query=query,
        step_code=code,
        step_prefix=bytes((channel,)),
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    )


NUMBERS: tuple[ViewSonicNumberEntityDescription, ...] = (
    ViewSonicNumberEntityDescription(
        key="brightness", translation_key="brightness", query=Query.BRIGHTNESS
    ),
    ViewSonicNumberEntityDescription(
        key="contrast", translation_key="contrast", query=Query.CONTRAST
    ),
    ViewSonicNumberEntityDescription(
        key="sharpness", translation_key="sharpness", query=Query.SHARPNESS
    ),
    ViewSonicNumberEntityDescription(
        key="hue",
        translation_key="hue",
        query=Query.HUE,
        entity_registry_enabled_default=False,
    ),
    ViewSonicNumberEntityDescription(
        key="saturation",
        translation_key="saturation",
        query=Query.SATURATION,
        entity_registry_enabled_default=False,
    ),
    ViewSonicNumberEntityDescription(
        key="gain",
        translation_key="gain",
        query=Query.GAIN,
        entity_registry_enabled_default=False,
    ),
    ViewSonicNumberEntityDescription(
        key="brilliant_color",
        translation_key="brilliant_color",
        query=Query.BRILLIANT_COLOR,
        direct=True,
        native_min_value=0,
        native_max_value=10,
        entity_registry_enabled_default=False,
    ),
    ViewSonicNumberEntityDescription(
        key="keystone_vertical",
        translation_key="keystone_vertical",
        query=Query.KEYSTONE_VERTICAL,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    ),
    ViewSonicNumberEntityDescription(
        key="keystone_horizontal",
        translation_key="keystone_horizontal",
        query=Query.KEYSTONE_HORIZONTAL,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    ),
    ViewSonicNumberEntityDescription(
        key="horizontal_position",
        translation_key="horizontal_position",
        query=Query.HORIZONTAL_POSITION,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    ),
    ViewSonicNumberEntityDescription(
        key="vertical_position",
        translation_key="vertical_position",
        query=Query.VERTICAL_POSITION,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    ),
    ViewSonicNumberEntityDescription(
        key="lens_shift_vertical",
        translation_key="lens_shift_vertical",
        query=Query.LENS_SHIFT_VERTICAL,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    ),
    ViewSonicNumberEntityDescription(
        key="lens_shift_horizontal",
        translation_key="lens_shift_horizontal",
        query=Query.LENS_SHIFT_HORIZONTAL,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    ),
    ViewSonicNumberEntityDescription(
        key="overscan",
        translation_key="overscan",
        query=Query.OVERSCAN,
        direct=True,
        native_min_value=0,
        native_max_value=5,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    ),
    _rgb("red_gain", Query.RED_GAIN, RGB_GAIN, 0),
    _rgb("green_gain", Query.GREEN_GAIN, RGB_GAIN, 1),
    _rgb("blue_gain", Query.BLUE_GAIN, RGB_GAIN, 2),
    _rgb("red_offset", Query.RED_OFFSET, RGB_OFFSET, 0),
    _rgb("green_offset", Query.GREEN_OFFSET, RGB_OFFSET, 1),
    _rgb("blue_offset", Query.BLUE_OFFSET, RGB_OFFSET, 2),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ViewSonicConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the projector numbers."""
    coordinator = entry.runtime_data
    async_add_entities(
        ViewSonicNumber(coordinator, description) for description in NUMBERS
    )


class ViewSonicNumber(ViewSonicQueryEntity, NumberEntity):
    """A numeric projector setting."""

    entity_description: ViewSonicNumberEntityDescription

    def __init__(
        self,
        coordinator: ViewSonicCoordinator,
        description: ViewSonicNumberEntityDescription,
    ) -> None:
        """Initialize the number."""
        super().__init__(coordinator, description, description.query)
        if (limits := coordinator.profile.ranges.get(description.key)) is not None:
            self._attr_native_min_value, self._attr_native_max_value = limits
            self._attr_mode = NumberMode.SLIDER
        elif description.direct:
            self._attr_mode = NumberMode.SLIDER
        else:
            # The real range is unknown for this model; a box avoids implying one.
            self._attr_mode = NumberMode.BOX

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        return self.raw_value

    async def async_set_native_value(self, value: float) -> None:
        """Change the value."""
        description = self.entity_description
        target = round(value)
        if description.direct:
            await self.coordinator.async_write(
                QUERIES[description.query].code, target, refresh=description.query
            )
            return
        await self.coordinator.async_step_to(
            description.query,
            description.step_code or QUERIES[description.query].code,
            target,
            prefix=description.step_prefix,
        )
