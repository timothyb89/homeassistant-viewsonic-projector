"""Base entities for the ViewSonic Projector integration."""

from typing import Any

from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import ViewSonicCoordinator
from .protocol import Query


class ViewSonicEntity(CoordinatorEntity[ViewSonicCoordinator]):
    """Common base for all ViewSonic projector entities."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: ViewSonicCoordinator, key: str, context: Any = None
    ) -> None:
        """Initialize the entity.

        ``context`` tells the coordinator which values to poll for this entity.
        """
        super().__init__(coordinator, context)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}-{key}"
        self._attr_device_info = coordinator.device_info


class ViewSonicQueryEntity(ViewSonicEntity):
    """An entity backed by a single queried value.

    Settings are only readable (and meaningful) while the projector is on, and
    the projector reports them as unavailable when greyed out in its menu, e.g.
    picture settings without an input signal.
    """

    entity_description: EntityDescription
    _query: Query
    _requires_on: bool = True

    def __init__(
        self,
        coordinator: ViewSonicCoordinator,
        description: EntityDescription,
        query: Query,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator, description.key, query)
        self.entity_description = description
        self._query = query

    @property
    def raw_value(self) -> Any:
        """Return the last value read from the projector."""
        return self.coordinator.value(self._query)

    @property
    def available(self) -> bool:
        """Return if the value is currently known."""
        return (
            super().available
            and (not self._requires_on or self.coordinator.is_on)
            and self.raw_value is not None
        )
