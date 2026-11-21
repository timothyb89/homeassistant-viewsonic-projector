"""Tests for the projector client over a real serialx transport."""

from collections.abc import AsyncGenerator
import contextlib
import socket
from unittest.mock import patch

import pytest

from custom_components.viewsonic_projector.client import (
    CommandDisabledError,
    ProjectorConnectionError,
    ProjectorTimeoutError,
    ViewSonicProjector,
)
from custom_components.viewsonic_projector.protocol import (
    COLOR_MODES,
    QUERIES,
    RGB_GAIN,
    PowerState,
    Query,
)

from .fake_projector import FakeProjector, addr


@pytest.fixture
async def client(projector: FakeProjector) -> AsyncGenerator[ViewSonicProjector]:
    """Return a client connected to the simulated projector."""
    client = ViewSonicProjector(projector.url)
    await client.connect()
    yield client
    await client.disconnect()


async def test_read_values(client: ViewSonicProjector) -> None:
    """Values of every width and signedness decode correctly."""
    assert await client.get_power_state() is PowerState.ON
    assert await client.read_value(Query.CONTRAST) == -10
    assert await client.read_value(Query.SHARPNESS) == 8
    assert await client.read_value(Query.LIGHT_SOURCE_HOURS) == 1234
    assert await client.read_value(Query.OPERATING_TEMPERATURE) == 29.7
    assert await client.read_value(Query.INPUT_SOURCE) == 0x03


async def test_write(client: ViewSonicProjector, projector: FakeProjector) -> None:
    """Writes are acknowledged and change the projector."""
    await client.write(QUERIES[Query.COLOR_MODE].code, COLOR_MODES["movie"])
    assert projector.value(Query.COLOR_MODE) == COLOR_MODES["movie"]


async def test_disabled(client: ViewSonicProjector, projector: FakeProjector) -> None:
    """The "disabled" reply maps to None for reads and an error for writes."""
    projector.disabled.add(addr(Query.COLOR_MODE))
    assert await client.read_value(Query.COLOR_MODE) is None
    with pytest.raises(CommandDisabledError):
        await client.write(QUERIES[Query.COLOR_MODE].code, 0)
    # Unsupported commands answer the same way.
    assert await client.read_value(Query.EOTF) is None


async def test_timeout_then_recovery(
    client: ViewSonicProjector, projector: FakeProjector
) -> None:
    """A missing reply times out without breaking later requests."""
    projector.silent.add(addr(Query.GAMMA))
    with pytest.raises(ProjectorTimeoutError):
        await client.read_value(Query.GAMMA)
    assert client.connected
    assert await client.read_value(Query.VOLUME) == 5


async def test_late_reply_is_not_mistaken_for_next(
    client: ViewSonicProjector, projector: FakeProjector
) -> None:
    """A reply arriving within the resync window after a timeout is discarded.

    Replies carry no command identifier, so after a timeout the client waits
    for a straggler before sending the next request.
    """
    projector.delays[addr(Query.BRIGHTNESS)] = 1.2  # timeout is 1s in tests
    with (
        patch("custom_components.viewsonic_projector.client._RESYNC_DELAY", 0.6),
        pytest.raises(ProjectorTimeoutError),
    ):
        await client.read_value(Query.BRIGHTNESS)
    projector.delays.clear()
    with patch("custom_components.viewsonic_projector.client._RESYNC_DELAY", 0.6):
        assert await client.read_value(Query.VOLUME) == 5
    assert await client.read_value(Query.SHARPNESS) == 8


async def test_step_to(client: ViewSonicProjector, projector: FakeProjector) -> None:
    """Increase/decrease-only values are stepped to the target."""
    code = QUERIES[Query.BRIGHTNESS].code
    assert await client.step_to(Query.BRIGHTNESS, code, 23) == 23
    assert projector.value(Query.BRIGHTNESS) == 23
    assert await client.step_to(Query.BRIGHTNESS, code, -7) == -7
    # Beyond the projector's limit it stops at the limit.
    assert await client.step_to(Query.BRIGHTNESS, code, -80) == -50


async def test_step_to_learns_inverted_direction(
    client: ViewSonicProjector, projector: FakeProjector
) -> None:
    """A step command that moves the wrong way is detected and compensated."""
    projector.inverted_steps.add(addr(Query.CONTRAST))
    code = QUERIES[Query.CONTRAST].code
    assert await client.step_to(Query.CONTRAST, code, 5) == 5
    writes_before = len(projector.writes())
    assert await client.step_to(Query.CONTRAST, code, 8) == 8
    # Once learned, no further detours are needed.
    assert len(projector.writes()) - writes_before == 3


async def test_step_to_with_channel_prefix(
    client: ViewSonicProjector, projector: FakeProjector
) -> None:
    """RGB gain steps carry the colour channel before the direction."""
    assert await client.step_to(Query.RED_GAIN, RGB_GAIN, 45, prefix=bytes((0,))) == 45
    assert projector.value(Query.RED_GAIN) == 45


async def test_step_to_disabled(
    client: ViewSonicProjector, projector: FakeProjector
) -> None:
    """Stepping an unavailable value raises."""
    projector.disabled.add(addr(Query.SHARPNESS))
    with pytest.raises(CommandDisabledError):
        await client.step_to(Query.SHARPNESS, QUERIES[Query.SHARPNESS].code, 3)


async def test_probe(client: ViewSonicProjector, projector: FakeProjector) -> None:
    """Probe reports the outcome of every query."""
    projector.silent.add(addr(Query.GAMMA))
    results = await client.probe()
    assert set(results) == {query.value for query in QUERIES}
    assert results["contrast"].as_dict() == {
        "status": "ok",
        "raw": "f6 ff",
        "value": -10,
    }
    assert results["eotf"].status == "disabled"
    assert results["gamma"].status == "timeout"


async def test_power(client: ViewSonicProjector, projector: FakeProjector) -> None:
    """Power commands change the power state."""
    await client.turn_off()
    assert await client.get_power_state() is PowerState.OFF
    # Settings are unavailable in standby.
    assert await client.read_value(Query.COLOR_MODE) is None
    await client.turn_on()
    assert await client.get_power_state() is PowerState.ON


async def test_connection_lost_and_reconnect(
    client: ViewSonicProjector, projector: FakeProjector
) -> None:
    """A dropped link is detected and the client can reconnect."""
    await projector.drop_connections()
    with pytest.raises(ProjectorConnectionError):
        await client.read_value(Query.VOLUME)
    assert not client.connected
    await client.connect()
    assert await client.read_value(Query.VOLUME) == 5


async def test_connect_failure(socket_enabled: None) -> None:
    """An unreachable port raises a connection error."""
    with contextlib.closing(socket.socket()) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    client = ViewSonicProjector(f"socket://127.0.0.1:{port}")
    with pytest.raises(ProjectorConnectionError):
        await client.connect()
    assert not client.connected


async def test_not_connected() -> None:
    """Commands before connecting raise a connection error."""
    client = ViewSonicProjector("socket://127.0.0.1:1")
    with pytest.raises(ProjectorConnectionError):
        await client.read_value(Query.POWER)


def test_safe_port_redacts_api_key() -> None:
    """ESPHome API keys in the port URL are not exposed."""
    client = ViewSonicProjector("esphome://aux2.local/?port_name=RS232&key=secret")
    assert "secret" not in client.safe_port
