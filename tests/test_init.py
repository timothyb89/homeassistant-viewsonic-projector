"""Tests for setting up, polling and unloading the integration."""

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.viewsonic_projector.const import DOMAIN
from custom_components.viewsonic_projector.protocol import PowerState, Query

from .conftest import entity_id
from .fake_projector import FakeProjector, addr


async def test_setup_and_unload(
    hass: HomeAssistant, init_integration: MockConfigEntry, projector: FakeProjector
) -> None:
    """The entry loads, creates a device and releases the port on unload."""
    assert init_integration.state is ConfigEntryState.LOADED
    (device,) = dr.async_entries_for_config_entry(
        dr.async_get(hass), init_integration.entry_id
    )
    assert (DOMAIN, init_integration.entry_id) in device.identifiers
    assert device.manufacturer == "ViewSonic"
    assert device.model == "LX700-4K"
    assert device.name == "ViewSonic LX700-4K"

    client = init_integration.runtime_data.client
    assert client.connected
    assert await hass.config_entries.async_unload(init_integration.entry_id)
    assert init_integration.state is ConfigEntryState.NOT_LOADED
    assert not client.connected


async def test_setup_retry_when_unreachable(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, projector: FakeProjector
) -> None:
    """Setup is retried when the projector does not answer."""
    projector.silent.add(addr_power := (0x11, 0x00))
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY
    projector.silent.discard(addr_power)


async def test_only_enabled_entities_are_polled(
    hass: HomeAssistant, init_integration: MockConfigEntry, projector: FakeProjector
) -> None:
    """Disabled-by-default entities do not cost a query."""
    reads = {
        (packet[8], packet[9]) for packet in projector.received if packet[0] == 0x07
    }
    assert (0x12, 0x0B) in reads  # color mode (enabled by default)
    assert (0x11, 0x2C) not in reads  # EOTF (disabled by default)


async def test_reconnect_after_link_loss(
    hass: HomeAssistant, init_integration: MockConfigEntry, projector: FakeProjector
) -> None:
    """Entities become unavailable when the link drops and recover after."""
    coordinator = init_integration.runtime_data
    media_player = entity_id(hass, "media_player", "projector")
    power_status = entity_id(hass, "sensor", "power_status")

    projector.silent.add((0x11, 0x00))
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(media_player).state == STATE_UNAVAILABLE
    assert hass.states.get(power_status).state == STATE_UNAVAILABLE

    projector.silent.clear()
    await projector.drop_connections()
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(media_player).state == "on"
    assert projector.connections == 2


async def test_refresh_fails_fast_when_projector_stops_answering(
    hass: HomeAssistant, init_integration: MockConfigEntry, projector: FakeProjector
) -> None:
    """If the projector goes silent mid-refresh, the update fails right away."""
    coordinator = init_integration.runtime_data
    before = len(projector.received)
    projector.silent_after = 1  # answer the power query only
    coordinator.invalidate_settings()
    await coordinator.async_refresh()
    assert not coordinator.last_update_success
    # Power, the first setting (timed out), then a liveness check (timed out).
    assert len(projector.received) - before == 3


@pytest.mark.usefixtures("enable_all_entities")
async def test_unanswered_query_is_skipped(
    hass: HomeAssistant, init_integration: MockConfigEntry, projector: FakeProjector
) -> None:
    """A query the projector never answers stops being polled until power-on."""
    coordinator = init_integration.runtime_data
    eotf = entity_id(hass, "select", "eotf")
    projector.silent.add(addr(Query.EOTF))

    def eotf_reads() -> int:
        return sum(
            1
            for packet in projector.received
            if packet[0] == 0x07 and (packet[8], packet[9]) == addr(Query.EOTF)
        )

    for _ in range(3):
        coordinator.invalidate_settings()
        await coordinator.async_refresh()
        assert coordinator.last_update_success
    assert eotf_reads() == 3  # initial read (answered "disabled") + 2 strikes
    assert hass.states.get(eotf).state == STATE_UNAVAILABLE
    # Other entities are unaffected.
    assert hass.states.get(entity_id(hass, "select", "color_mode")).state == "standard"

    # After the projector is turned on again, it is asked once more.
    projector.silent.clear()
    projector.power = PowerState.OFF
    await coordinator.async_refresh()
    projector.power = PowerState.ON
    projector.set_value(Query.EOTF, 1)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(eotf).state == "mid"
