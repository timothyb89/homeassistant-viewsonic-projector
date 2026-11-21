"""Tests for actions, diagnostics, standby behaviour and serial proxy ports."""

from unittest.mock import patch

from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.const import CONF_DEVICE
from homeassistant.core import HomeAssistant, State
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er, restore_state as rs
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.viewsonic_projector.const import (
    CONF_BAUD_RATE,
    CONF_MODEL,
    DOMAIN,
)
from custom_components.viewsonic_projector.protocol import PowerState, Query

from .conftest import entity_id
from .fake_projector import FakeProjector, addr


async def test_probe(
    hass: HomeAssistant, init_integration: MockConfigEntry, projector: FakeProjector
) -> None:
    """Probe returns the raw outcome of every query."""
    result = await hass.services.async_call(
        DOMAIN,
        "probe",
        {"config_entry_id": init_integration.entry_id},
        blocking=True,
        return_response=True,
    )
    assert result["power_state"] == "on"
    assert result["results"]["color_mode"] == {
        "status": "ok",
        "raw": "04",
        "value": 4,
    }
    assert result["results"]["eotf"]["status"] == "disabled"


async def test_read_and_write(
    hass: HomeAssistant, init_integration: MockConfigEntry, projector: FakeProjector
) -> None:
    """Raw read and write actions."""
    result = await hass.services.async_call(
        DOMAIN,
        "read",
        {"config_entry_id": init_integration.entry_id, "code": "0x12 0x02"},
        blocking=True,
        return_response=True,
    )
    assert result == {"status": "ok", "data": "f6 ff", "unsigned": 65526, "signed": -10}

    result = await hass.services.async_call(
        DOMAIN,
        "write",
        {
            "config_entry_id": init_integration.entry_id,
            "code": "12 0B",
            "data": "0x13",
        },
        blocking=True,
        return_response=True,
    )
    assert result == {"status": "ok"}
    assert projector.value(Query.COLOR_MODE) == 0x13

    result = await hass.services.async_call(
        DOMAIN,
        "write",
        {"config_entry_id": init_integration.entry_id, "code": "0x11 0x2C"},
        blocking=True,
        return_response=True,
    )
    assert result == {"status": "disabled"}


async def test_action_validation(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Invalid input and unknown entries are rejected."""
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "read",
            {"config_entry_id": "nope", "code": "0x12 0x02"},
            blocking=True,
            return_response=True,
        )
    with pytest.raises(Exception, match="cmd2 cmd3"):
        await hass.services.async_call(
            DOMAIN,
            "read",
            {"config_entry_id": init_integration.entry_id, "code": "0x12"},
            blocking=True,
            return_response=True,
        )
    with pytest.raises(Exception, match="hex bytes"):
        await hass.services.async_call(
            DOMAIN,
            "write",
            {
                "config_entry_id": init_integration.entry_id,
                "code": "0x12 0x0B",
                "data": "zz",
            },
            blocking=True,
            return_response=True,
        )


async def test_action_during_warm_up(
    hass: HomeAssistant, init_integration: MockConfigEntry, projector: FakeProjector
) -> None:
    """The specification forbids commands while warming up."""
    projector.power = PowerState.WARMING_UP
    await init_integration.runtime_data.async_refresh()
    with pytest.raises(HomeAssistantError, match="warming up"):
        await hass.services.async_call(
            DOMAIN,
            "read",
            {"config_entry_id": init_integration.entry_id, "code": "0x12 0x02"},
            blocking=True,
            return_response=True,
        )


async def test_diagnostics(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    init_integration: MockConfigEntry,
) -> None:
    """Diagnostics include state and the error counters."""
    assert await async_setup_component(hass, "diagnostics", {})
    diagnostics = await get_diagnostics_for_config_entry(
        hass, hass_client, init_integration
    )
    assert diagnostics["connected"] is True
    assert diagnostics["data"]["power"] == "ON"
    assert diagnostics["data"]["color_mode"] == 4
    assert diagnostics["profile"]["volume_max"] == 10
    # The simulator does not implement the error status query.
    assert diagnostics["error_status"] == "disabled"


async def test_hours_read_in_standby_and_restored(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, projector: FakeProjector
) -> None:
    """Light source hours survive standby and restarts."""
    projector.power = PowerState.OFF
    projector.standby_readable.clear()
    mock_config_entry.add_to_hass(hass)
    # Home Assistant 2026.11 keys restored states by entity registry ID, which
    # the 2026.10 harness's mock_restore_cache_with_extra_data does not do.
    registry_entry = er.async_get(hass).async_get_or_create(
        "sensor",
        DOMAIN,
        f"{mock_config_entry.entry_id}-light_source_hours",
        config_entry=mock_config_entry,
    )
    restore_data = rs.RestoreStateData(hass)
    restore_data.last_states_by_entity_registry_id[registry_entry.id] = rs.StoredState(
        State(registry_entry.entity_id, "1200"),
        rs.RestoredExtraData({"native_value": 1200, "native_unit_of_measurement": "h"}),
        dt_util.utcnow(),
        entity_registry_id=registry_entry.id,
    )
    rs.async_get.cache_clear()
    hass.data[rs.DATA_RESTORE_STATE] = restore_data
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    hours = entity_id(hass, "sensor", "light_source_hours")
    # The projector does not answer in standby, so the restored value is kept.
    assert hass.states.get(hours).state == "1200"

    # Turned on: the current value is read.
    projector.power = PowerState.ON
    coordinator = mock_config_entry.runtime_data
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(hours).state == "1234"

    # Turned off again: tried once in standby, then left alone.
    projector.power = PowerState.OFF
    projector.standby_readable.add(addr(Query.LIGHT_SOURCE_HOURS))
    projector.set_value(Query.LIGHT_SOURCE_HOURS, 1240)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(hours).state == "1240"
    projector.set_value(Query.LIGHT_SOURCE_HOURS, 9999)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(hours).state == "1240"


SERIAL_PROXY_URL = "esphome-hass://esphome/0123456789abcdef?port_name=RS232"


async def test_serial_proxy_not_ready(hass: HomeAssistant) -> None:
    """A serial proxy whose ESPHome device is not loaded is retried later."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_DEVICE: SERIAL_PROXY_URL, CONF_BAUD_RATE: 115200, CONF_MODEL: "x"},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_serial_proxy_in_config_flow(hass: HomeAssistant) -> None:
    """The flow reports a serial proxy that cannot be opened yet."""
    assert await async_setup_component(hass, "usb", {})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_DEVICE: SERIAL_PROXY_URL, CONF_BAUD_RATE: "115200", CONF_MODEL: "x"},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_port_url_passed_to_serialx(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, projector: FakeProjector
) -> None:
    """The selected port URL and baud rate reach serialx unchanged."""
    import serialx  # noqa: PLC0415

    real_open = serialx.open_serial_connection
    with patch(
        "custom_components.viewsonic_projector.client.serialx.open_serial_connection",
        side_effect=real_open,
    ) as mock_open:
        mock_config_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
    mock_open.assert_called_once_with(projector.url, baudrate=115200)
