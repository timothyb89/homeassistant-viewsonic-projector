"""Switch entities for the ViewSonic Projector integration."""

from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ViewSonicConfigEntry, ViewSonicCoordinator
from .entity import ViewSonicQueryEntity
from .protocol import AUDIO_MODE, QUERIES, SPDIF_OFF, SPDIF_ON, Code, Query

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class ViewSonicSwitchEntityDescription(SwitchEntityDescription):
    """Describes a projector on/off setting."""

    query: Query
    # Defaults to the query's own address.
    write_code: Code | None = None
    on_data: int = 1
    off_data: int = 0
    # Value the query returns when the setting is on.
    on_value: int = 1


SWITCHES: tuple[ViewSonicSwitchEntityDescription, ...] = (
    ViewSonicSwitchEntityDescription(
        key="blank", translation_key="blank", query=Query.BLANK
    ),
    ViewSonicSwitchEntityDescription(
        key="freeze", translation_key="freeze", query=Query.FREEZE
    ),
    ViewSonicSwitchEntityDescription(
        key="hdmi_cec",
        translation_key="hdmi_cec",
        query=Query.HDMI_CEC,
        entity_category=EntityCategory.CONFIG,
    ),
    ViewSonicSwitchEntityDescription(
        key="quick_auto_search",
        translation_key="quick_auto_search",
        query=Query.QUICK_AUTO_SEARCH,
        entity_category=EntityCategory.CONFIG,
    ),
    ViewSonicSwitchEntityDescription(
        key="high_altitude",
        translation_key="high_altitude",
        query=Query.HIGH_ALTITUDE,
        entity_category=EntityCategory.CONFIG,
    ),
    ViewSonicSwitchEntityDescription(
        key="quick_power_off",
        translation_key="quick_power_off",
        query=Query.QUICK_POWER_OFF,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    ),
    ViewSonicSwitchEntityDescription(
        key="osd_messages",
        translation_key="osd_messages",
        query=Query.OSD_MESSAGES,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    ),
    ViewSonicSwitchEntityDescription(
        key="three_d_sync_invert",
        translation_key="three_d_sync_invert",
        query=Query.THREE_D_SYNC_INVERT,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    ),
    ViewSonicSwitchEntityDescription(
        key="isf_mode",
        translation_key="isf_mode",
        query=Query.ISF_MODE,
        entity_registry_enabled_default=False,
    ),
    ViewSonicSwitchEntityDescription(
        key="projection_360",
        translation_key="projection_360",
        query=Query.PROJECTION_360,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    ),
    # S/PDIF is switched through the audio mode command but read on its own
    # address, where the specification lists 0 for on and 1 for off.
    ViewSonicSwitchEntityDescription(
        key="spdif",
        translation_key="spdif",
        query=Query.SPDIF,
        write_code=AUDIO_MODE,
        on_data=SPDIF_ON,
        off_data=SPDIF_OFF,
        on_value=0,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ViewSonicConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the projector switches."""
    coordinator = entry.runtime_data
    async_add_entities(
        ViewSonicSwitch(coordinator, description) for description in SWITCHES
    )


class ViewSonicSwitch(ViewSonicQueryEntity, SwitchEntity):
    """A projector on/off setting."""

    entity_description: ViewSonicSwitchEntityDescription

    def __init__(
        self,
        coordinator: ViewSonicCoordinator,
        description: ViewSonicSwitchEntityDescription,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, description, description.query)
        self._write_code = description.write_code or QUERIES[description.query].code

    @property
    def is_on(self) -> bool | None:
        """Return whether the setting is on."""
        value = self.raw_value
        return None if value is None else value == self.entity_description.on_value

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the setting on."""
        await self.coordinator.async_write(
            self._write_code, self.entity_description.on_data, refresh=self._query
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the setting off."""
        await self.coordinator.async_write(
            self._write_code, self.entity_description.off_data, refresh=self._query
        )
