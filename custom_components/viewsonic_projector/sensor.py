"""Sensor entities for the ViewSonic Projector integration."""

from dataclasses import dataclass

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from .coordinator import ViewSonicConfigEntry, ViewSonicCoordinator
from .entity import ViewSonicEntity, ViewSonicQueryEntity
from .protocol import PowerState, Query

PARALLEL_UPDATES = 0

POWER_STATUS_OPTIONS = [state.name.lower() for state in PowerState]


@dataclass(frozen=True, kw_only=True)
class ViewSonicSensorEntityDescription(SensorEntityDescription):
    """Describes a projector value sensor."""

    query: Query
    requires_on: bool = True


SENSORS: tuple[ViewSonicSensorEntityDescription, ...] = (
    ViewSonicSensorEntityDescription(
        key="light_source_hours",
        translation_key="light_source_hours",
        query=Query.LIGHT_SOURCE_HOURS,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        requires_on=False,
    ),
    ViewSonicSensorEntityDescription(
        key="equivalent_light_source_hours",
        translation_key="equivalent_light_source_hours",
        query=Query.EQUIVALENT_LIGHT_SOURCE_HOURS,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        requires_on=False,
    ),
    ViewSonicSensorEntityDescription(
        key="operating_temperature",
        translation_key="operating_temperature",
        query=Query.OPERATING_TEMPERATURE,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ViewSonicConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the projector sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            ViewSonicPowerStatusSensor(coordinator),
            *(ViewSonicSensor(coordinator, description) for description in SENSORS),
        ]
    )


class ViewSonicPowerStatusSensor(ViewSonicEntity, SensorEntity):
    """Detailed power state, available while the projector is in standby."""

    _attr_translation_key = "power_status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = POWER_STATUS_OPTIONS

    def __init__(self, coordinator: ViewSonicCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "power_status", Query.POWER)

    @property
    def native_value(self) -> str | None:
        """Return the power state."""
        state = self.coordinator.power_state
        return None if state is None else state.name.lower()


class ViewSonicSensor(ViewSonicQueryEntity, RestoreSensor):
    """A value read from the projector.

    Values that do not change while the projector is in standby keep their
    last reading (also across restarts) when the projector cannot be asked.
    """

    entity_description: ViewSonicSensorEntityDescription

    def __init__(
        self,
        coordinator: ViewSonicCoordinator,
        description: ViewSonicSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, description, description.query)
        self._requires_on = description.requires_on
        self._restored: StateType = None

    async def async_added_to_hass(self) -> None:
        """Restore the last reading for values kept while in standby."""
        await super().async_added_to_hass()
        if (
            not self._requires_on
            and (last := await self.async_get_last_sensor_data()) is not None
        ):
            self._restored = last.native_value  # type: ignore[assignment]

    @property
    def raw_value(self) -> StateType:
        """Return the reading, falling back to the restored one."""
        value = super().raw_value
        if value is None and not self._requires_on:
            return self._restored
        return value

    @property
    def native_value(self) -> StateType:
        """Return the reading."""
        return self.raw_value
