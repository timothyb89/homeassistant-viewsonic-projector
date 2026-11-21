"""Tests for the ViewSonic Projector config flow."""

from collections.abc import Generator
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_DEVICE, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.viewsonic_projector.const import (
    CONF_BAUD_RATE,
    CONF_MODEL,
    CONF_SETTINGS_INTERVAL,
    CONF_SOURCES,
    DOMAIN,
)

from .fake_projector import FakeProjector

CLOSED_PORT = "socket://127.0.0.1:1"


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Do not set up the entry created by the flow."""
    with patch(
        "custom_components.viewsonic_projector.async_setup_entry", return_value=None
    ) as mock:
        yield mock


@pytest.mark.usefixtures("mock_setup_entry")
async def test_user_flow(hass: HomeAssistant, projector: FakeProjector) -> None:
    """A reachable projector creates an entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_DEVICE: projector.url, CONF_BAUD_RATE: "115200", CONF_MODEL: "LX700-4K"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "ViewSonic LX700-4K"
    assert result["data"] == {
        CONF_DEVICE: projector.url,
        CONF_BAUD_RATE: 115200,
        CONF_MODEL: "LX700-4K",
    }


@pytest.mark.usefixtures("mock_setup_entry", "socket_enabled")
async def test_user_flow_cannot_connect(
    hass: HomeAssistant, projector: FakeProjector
) -> None:
    """An unreachable port shows an error and allows a retry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_DEVICE: CLOSED_PORT, CONF_BAUD_RATE: "9600", CONF_MODEL: "PX701-4K"},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_DEVICE: projector.url, CONF_BAUD_RATE: "9600", CONF_MODEL: "PX701-4K"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_BAUD_RATE] == 9600


@pytest.mark.usefixtures("mock_setup_entry")
async def test_user_flow_no_response(
    hass: HomeAssistant, projector: FakeProjector
) -> None:
    """A silent projector leads to the troubleshooting step."""
    projector.silent.add(addr_power := (0x11, 0x00))
    user_input = {
        CONF_DEVICE: projector.url,
        CONF_BAUD_RATE: "115200",
        CONF_MODEL: "LX700-4K",
    }
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "troubleshoot"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    projector.silent.discard(addr_power)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.usefixtures("mock_setup_entry")
async def test_user_flow_unexpected_error(
    hass: HomeAssistant, projector: FakeProjector
) -> None:
    """Unexpected errors are reported as unknown."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    with patch(
        "custom_components.viewsonic_projector.config_flow.ViewSonicProjector.connect",
        side_effect=RuntimeError("boom"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_DEVICE: projector.url,
                CONF_BAUD_RATE: "115200",
                CONF_MODEL: "LX700-4K",
            },
        )
    assert result["errors"] == {"base": "unknown"}


async def test_user_flow_already_configured(
    hass: HomeAssistant, projector: FakeProjector, mock_config_entry: MockConfigEntry
) -> None:
    """The same port cannot be configured twice."""
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_DEVICE: projector.url, CONF_BAUD_RATE: "115200", CONF_MODEL: "x"},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.usefixtures("mock_setup_entry")
async def test_reconfigure(
    hass: HomeAssistant, projector: FakeProjector, mock_config_entry: MockConfigEntry
) -> None:
    """The port, baud rate and model can be changed."""
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_DEVICE: CLOSED_PORT, CONF_BAUD_RATE: "19200", CONF_MODEL: "PA503W"},
    )
    assert result["errors"] == {"base": "cannot_connect"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_DEVICE: projector.url, CONF_BAUD_RATE: "19200", CONF_MODEL: "PA503W"},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data[CONF_BAUD_RATE] == 19200
    assert mock_config_entry.title == "ViewSonic PA503W"


async def test_options_flow(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Options are stored and the entry reloaded."""
    result = await hass.config_entries.options.async_init(init_integration.entry_id)
    assert result["type"] is FlowResultType.FORM
    schema_defaults = {str(key): key.default() for key in result["data_schema"].schema}
    # The LX700-4K profile only offers its two HDMI inputs by default.
    assert schema_defaults[CONF_SOURCES] == ["hdmi_1", "hdmi_2"]

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_SCAN_INTERVAL: 10,
            CONF_SETTINGS_INTERVAL: 60,
            CONF_SOURCES: ["hdmi_2"],
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert init_integration.options == {
        CONF_SCAN_INTERVAL: 10,
        CONF_SETTINGS_INTERVAL: 60,
        CONF_SOURCES: ["hdmi_2"],
    }
    state = hass.states.get("media_player.viewsonic_lx700_4k")
    assert state is not None
    assert state.attributes["source_list"] == ["hdmi_2"]
