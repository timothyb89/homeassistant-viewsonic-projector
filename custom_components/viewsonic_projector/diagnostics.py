"""Diagnostics support for the ViewSonic Projector integration."""

from dataclasses import asdict
from typing import Any

from homeassistant.const import CONF_DEVICE
from homeassistant.core import HomeAssistant

from .client import ProjectorError
from .coordinator import ViewSonicConfigEntry
from .protocol import QUERIES, PowerState, Query


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ViewSonicConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    client = coordinator.client

    # The service-only error counters (fan, thermal sensor, light source...).
    error_status: str | None = None
    if client.connected and coordinator.power_state is PowerState.ON:
        try:
            reply = await client.read(QUERIES[Query.ERROR_STATUS].code)
        except ProjectorError as err:
            error_status = f"error: {err}"
        else:
            error_status = "disabled" if reply is None else reply.data.hex(" ")

    data = coordinator.data or {}
    return {
        "entry": {
            "title": entry.title,
            # A raw esphome:// URL may carry an API key in its query string.
            "data": {**entry.data, CONF_DEVICE: client.safe_port},
            "options": dict(entry.options),
        },
        "profile": asdict(coordinator.profile),
        "connected": client.connected,
        "last_update_success": coordinator.last_update_success,
        "polled_queries": sorted(coordinator.polled_queries()),
        "data": {
            str(key): value.name if isinstance(value, PowerState) else value
            for key, value in data.items()
        },
        "error_status": error_status,
    }
