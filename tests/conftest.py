"""Fixtures for ViewSonic Projector tests."""

from collections.abc import AsyncGenerator, Generator
from unittest.mock import patch

from homeassistant.const import CONF_DEVICE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.viewsonic_projector.const import (
    CONF_BAUD_RATE,
    CONF_MODEL,
    DOMAIN,
)

from .fake_projector import FakeProjector


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable loading the custom integration."""


@pytest.fixture(autouse=True)
def fast_client() -> Generator[None]:
    """Keep protocol pacing and timeouts short in tests."""
    with (
        patch("custom_components.viewsonic_projector.client.DEFAULT_TIMEOUT", 1.0),
        patch(
            "custom_components.viewsonic_projector.client.DEFAULT_COMMAND_INTERVAL", 0
        ),
        patch("custom_components.viewsonic_projector.client._RESYNC_DELAY", 0.05),
    ):
        yield


@pytest.fixture
async def projector(socket_enabled: None) -> AsyncGenerator[FakeProjector]:
    """Return a running simulated projector (served on 127.0.0.1)."""
    fake = FakeProjector()
    await fake.start()
    yield fake
    await fake.stop()


@pytest.fixture
def mock_config_entry(projector: FakeProjector) -> MockConfigEntry:
    """Return a config entry for the simulated projector."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="ViewSonic LX700-4K",
        data={
            CONF_DEVICE: projector.url,
            CONF_BAUD_RATE: 115200,
            CONF_MODEL: "LX700-4K",
        },
    )


@pytest.fixture
def enable_all_entities() -> Generator[None]:
    """Create entities that are disabled by default as enabled."""
    with patch(
        "homeassistant.helpers.entity.Entity.entity_registry_enabled_default", True
    ):
        yield


@pytest.fixture
async def init_integration(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> MockConfigEntry:
    """Set up the integration and wait for the initial settings refresh."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return mock_config_entry


def entity_id(hass: HomeAssistant, platform: str, key: str) -> str:
    """Look up an entity ID by its unique ID key."""
    registry = er.async_get(hass)
    entries = [
        entry
        for entry in registry.entities.values()
        if entry.platform == DOMAIN
        and entry.domain == platform
        and entry.unique_id.endswith(f"-{key}")
    ]
    assert len(entries) == 1, f"{platform}.{key}: {entries}"
    return entries[0].entity_id
