"""Actions for the ViewSonic Projector integration."""

from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
import homeassistant.helpers.config_validation as cv
import probatio

from .client import CommandDisabledError
from .const import DOMAIN
from .coordinator import ViewSonicConfigEntry, ViewSonicCoordinator
from .protocol import Code

SERVICE_PROBE = "probe"
SERVICE_READ = "read"
SERVICE_WRITE = "write"

ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_CODE = "code"
ATTR_DATA = "data"


def hex_bytes(value: Any) -> bytes:
    """Parse whitespace or comma separated hex bytes, e.g. ``0x12 0x0B``."""
    tokens = str(value).replace(",", " ").split()
    try:
        result = bytes(int(token, 16) for token in tokens)
    except ValueError as err:
        raise probatio.Invalid(
            f"Expected hex bytes such as '0x12 0x0B', got {value!r}"
        ) from err
    if not result:
        raise probatio.Invalid("At least one byte is required")
    return result


def command_code(value: Any) -> Code:
    """Parse a ``cmd2 cmd3`` command address."""
    raw = hex_bytes(value)
    if len(raw) != 2:
        raise probatio.Invalid(
            f"Expected two bytes (cmd2 cmd3) such as '0x12 0x0B', got {value!r}"
        )
    return Code(raw[0], raw[1])


_ENTRY_SCHEMA = {probatio.Required(ATTR_CONFIG_ENTRY_ID): cv.string}

PROBE_SCHEMA = probatio.Schema(_ENTRY_SCHEMA)
READ_SCHEMA = probatio.Schema(
    {**_ENTRY_SCHEMA, probatio.Required(ATTR_CODE): command_code}
)
WRITE_SCHEMA = probatio.Schema(
    {
        **_ENTRY_SCHEMA,
        probatio.Required(ATTR_CODE): command_code,
        probatio.Optional(ATTR_DATA, default="0x00"): hex_bytes,
    }
)


def _coordinator(hass: HomeAssistant, call: ServiceCall) -> ViewSonicCoordinator:
    entry_id: str = call.data[ATTR_CONFIG_ENTRY_ID]
    entry: ViewSonicConfigEntry | None = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="entry_not_found",
            translation_placeholders={"entry_id": entry_id},
        )
    if entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="entry_not_loaded",
            translation_placeholders={"entry_id": entry_id},
        )
    return entry.runtime_data


async def _async_probe(call: ServiceCall) -> ServiceResponse:
    coordinator = _coordinator(call.hass, call)
    coordinator.ensure_ready(require_on=False)
    results = await coordinator.async_command(coordinator.client.probe())
    power = coordinator.power_state
    return {
        "power_state": None if power is None else power.name.lower(),
        "results": {key: result.as_dict() for key, result in results.items()},
    }


async def _async_read(call: ServiceCall) -> ServiceResponse:
    coordinator = _coordinator(call.hass, call)
    coordinator.ensure_ready(require_on=False)
    code: Code = call.data[ATTR_CODE]
    reply = await coordinator.async_command(coordinator.client.read(code))
    if reply is None:
        return {"status": "disabled"}
    return {
        "status": "ok",
        "data": reply.data.hex(" "),
        "unsigned": reply.as_int(),
        "signed": reply.as_int(signed=True),
    }


async def _async_write(call: ServiceCall) -> ServiceResponse:
    coordinator = _coordinator(call.hass, call)
    coordinator.ensure_ready(require_on=False)
    code: Code = call.data[ATTR_CODE]
    data: bytes = call.data[ATTR_DATA]

    async def _write() -> str:
        try:
            await coordinator.client.write(code, data)
        except CommandDisabledError:
            return "disabled"
        return "ok"

    status = await coordinator.async_command(_write())
    await coordinator.async_request_settings_refresh()
    return {"status": status} if call.return_response else None


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the integration's actions."""
    hass.services.async_register(
        DOMAIN,
        SERVICE_PROBE,
        _async_probe,
        schema=PROBE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_READ,
        _async_read,
        schema=READ_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_WRITE,
        _async_write,
        schema=WRITE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
