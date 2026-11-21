"""Async client for ViewSonic projectors.

Works with any port URL understood by ``serialx``: local devices
(``/dev/ttyUSB0``, ``COM3``), ``socket://host:port`` bridges, ESPHome serial
proxies (``esphome://``) and, inside Home Assistant, the ``esphome-hass://``
URLs that the serial port selector produces for ESPHome devices such as the
Home Assistant Connect AUX-2. This module has no Home Assistant dependencies.
"""

import asyncio
import contextlib
from dataclasses import dataclass
import logging
from typing import Any

import serialx

from .protocol import (
    DEFAULT_BAUD_RATE,
    DIRECTION_DECREASE,
    DIRECTION_INCREASE,
    POWER_OFF,
    POWER_ON,
    QUERIES,
    Code,
    PacketType,
    PowerState,
    Query,
    Reply,
    ReplyParser,
    build_read,
    build_write,
    decode_value,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 2.0
# Idle time between the end of one exchange and the next request.
DEFAULT_COMMAND_INTERVAL = 0.05
# After a timed-out request, wait this long so a late reply can arrive and be
# discarded instead of being mistaken for the reply to the next request.
_RESYNC_DELAY = 0.5
# Increase/decrease commands sent before reading the value back.
_MAX_STEP_BATCH = 10
_MAX_STEP_ROUNDS = 40


class ProjectorError(Exception):
    """Base class for projector errors."""


class ProjectorConnectionError(ProjectorError):
    """The serial port could not be opened or the connection was lost."""


class ProjectorTimeoutError(ProjectorError, TimeoutError):
    """The projector did not reply in time."""


class CommandDisabledError(ProjectorError):
    """The projector reported the function as unavailable right now.

    The projector replies this way when the function is greyed out in its
    on-screen menu, e.g. picture settings without an input signal, or when the
    model does not implement the command.
    """


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """Outcome of reading one query during a probe."""

    status: str  # "ok", "disabled", "timeout"
    raw: str | None = None
    value: int | float | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON serialisable representation."""
        return {"status": self.status, "raw": self.raw, "value": self.value}


class ViewSonicProjector:
    """A ViewSonic projector reachable over a serial connection."""

    def __init__(
        self,
        port: str,
        baudrate: int = DEFAULT_BAUD_RATE,
        *,
        timeout: float | None = None,
        command_interval: float | None = None,
    ) -> None:
        """Initialize the client; call `connect` before sending commands."""
        self._port = port
        self._baudrate = baudrate
        self._timeout = DEFAULT_TIMEOUT if timeout is None else timeout
        self._command_interval = (
            DEFAULT_COMMAND_INTERVAL if command_interval is None else command_interval
        )
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._read_task: asyncio.Task[None] | None = None
        self._replies: asyncio.Queue[Reply | None] = asyncio.Queue()
        self._parser = ReplyParser()
        self._lock = asyncio.Lock()
        self._connected = False
        self._last_exchange = 0.0
        self._resync_needed = False
        # Step commands found to move the value opposite to the documentation.
        self._inverted_steps: set[tuple[Code, bytes]] = set()

    @property
    def port(self) -> str:
        """Return the port URL."""
        return self._port

    @property
    def safe_port(self) -> str:
        """Return the port URL with secrets (e.g. API keys) redacted."""
        return serialx.redact_uri(self._port)

    @property
    def baudrate(self) -> int:
        """Return the configured baud rate."""
        return self._baudrate

    @property
    def connected(self) -> bool:
        """Return whether the serial connection is open."""
        return self._connected

    # -- Connection lifecycle ------------------------------------------------

    async def connect(self) -> None:
        """Open the serial connection."""
        if self._connected:
            return
        try:
            self._reader, self._writer = await serialx.open_serial_connection(
                self._port, baudrate=self._baudrate
            )
        except (serialx.SerialException, OSError, ValueError) as err:
            raise ProjectorConnectionError(
                f"Unable to open {self.safe_port}: {err}"
            ) from err

        self._parser.reset()
        self._replies = asyncio.Queue()
        self._resync_needed = False
        self._connected = True
        self._read_task = asyncio.create_task(
            self._read_loop(self._reader), name=f"viewsonic_projector {self.safe_port}"
        )
        _LOGGER.debug("Connected to %s at %s baud", self.safe_port, self._baudrate)

    async def disconnect(self) -> None:
        """Close the serial connection."""
        await self._teardown()

    async def _teardown(self) -> None:
        if not self._connected and self._read_task is None and self._writer is None:
            return
        self._connected = False
        read_task, self._read_task = self._read_task, None
        writer, self._writer = self._writer, None
        self._reader = None
        # Wake up a request that is waiting for a reply.
        self._replies.put_nowait(None)

        if read_task is not None and read_task is not asyncio.current_task():
            read_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await read_task

        if writer is not None:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                _LOGGER.debug("Error closing %s", self.safe_port, exc_info=True)
        _LOGGER.debug("Disconnected from %s", self.safe_port)

    async def _read_loop(self, reader: asyncio.StreamReader) -> None:
        try:
            while True:
                data = await reader.read(256)
                if not data:
                    _LOGGER.debug("Serial connection to %s closed", self.safe_port)
                    break
                for reply in self._parser.feed(data):
                    self._replies.put_nowait(reply)
        except asyncio.CancelledError:
            raise
        except Exception as err:
            _LOGGER.debug("Error reading from %s: %s", self.safe_port, err)
        # The connection is gone; tear down without awaiting ourselves.
        if self._read_task is asyncio.current_task():
            self._read_task = None
            await self._teardown()

    # -- Request/response ----------------------------------------------------

    def _discard_pending_replies(self) -> None:
        while not self._replies.empty():
            reply = self._replies.get_nowait()
            if reply is not None:
                _LOGGER.debug("Discarding stale reply %s", reply.raw().hex(" "))

    async def _exchange(self, packet: bytes, expected: PacketType) -> Reply:
        """Send a packet and return the matching reply.

        Replies do not identify the command they answer, so only one request
        may be outstanding at a time.
        """
        async with self._lock:
            if not self._connected or self._writer is None:
                raise ProjectorConnectionError(f"Not connected to {self.safe_port}")

            loop = asyncio.get_running_loop()
            delay = self._last_exchange + self._command_interval - loop.time()
            if self._resync_needed:
                delay = max(delay, self._last_exchange + _RESYNC_DELAY - loop.time())
                self._resync_needed = False
            if delay > 0:
                await asyncio.sleep(delay)
            self._discard_pending_replies()

            _LOGGER.debug("Sending %s", packet.hex(" "))
            try:
                self._writer.write(packet)
                await self._writer.drain()
            except Exception as err:
                await self._teardown()
                raise ProjectorConnectionError(
                    f"Error writing to {self.safe_port}: {err}"
                ) from err

            try:
                async with asyncio.timeout(self._timeout):
                    while True:
                        reply = await self._replies.get()
                        if reply is None:
                            raise ProjectorConnectionError(
                                f"Connection to {self.safe_port} lost"
                            )
                        _LOGGER.debug("Received %s", reply.raw().hex(" "))
                        if reply.type in (expected, PacketType.DISABLED):
                            return reply
                        _LOGGER.debug("Ignoring unexpected %s reply", reply.type.name)
            except TimeoutError:
                self._resync_needed = True
                raise ProjectorTimeoutError(
                    f"No reply from projector on {self.safe_port} to {packet.hex(' ')}"
                ) from None
            finally:
                self._last_exchange = loop.time()

    async def read(self, code: Code) -> Reply | None:
        """Send a read command; return None if the function is unavailable."""
        reply = await self._exchange(
            build_read(code.cmd2, code.cmd3), PacketType.READ_RESPONSE
        )
        return None if reply.type is PacketType.DISABLED else reply

    async def write(self, code: Code, data: bytes | int = 0) -> None:
        """Send a write command, raising CommandDisabledError if refused."""
        reply = await self._exchange(
            build_write(code.cmd2, code.cmd3, data), PacketType.WRITE_ACK
        )
        if reply.type is PacketType.DISABLED:
            raise CommandDisabledError(f"Projector refused command {code}")

    async def send_raw(self, packet: bytes) -> Reply:
        """Send a complete packet and return whatever reply comes back."""
        expected = (
            PacketType.WRITE_ACK
            if packet[:1] == bytes((PacketType.WRITE,))
            else PacketType.READ_RESPONSE
        )
        return await self._exchange(packet, expected)

    # -- Typed helpers -----------------------------------------------------------

    async def read_value(self, query: Query) -> int | float | None:
        """Read and decode a value; None if the function is unavailable."""
        reply = await self.read(QUERIES[query].code)
        return None if reply is None else decode_value(query, reply)

    async def get_power_state(self) -> PowerState:
        """Return the power state."""
        value = await self.read_value(Query.POWER)
        if value is None:
            raise CommandDisabledError("Projector refused the power status query")
        try:
            return PowerState(int(value))
        except ValueError as err:
            raise ProjectorError(f"Unknown power state {value!r}") from err

    async def turn_on(self) -> None:
        """Turn the projector on."""
        await self.write(POWER_ON)

    async def turn_off(self) -> None:
        """Turn the projector off."""
        await self.write(POWER_OFF)

    async def step_to(
        self, query: Query, step: Code, target: int, *, prefix: bytes = b""
    ) -> int:
        """Move a value that only supports increase/decrease commands to target.

        ``prefix`` is sent before the direction byte (e.g. the colour channel of
        the RGB gain commands). Stops at the projector's limits. Returns the
        value read back at the end.
        """
        current = await self.read_value(query)
        if current is None:
            raise CommandDisabledError(f"{query} is not available")
        current = int(current)
        step_key = (step, prefix)
        step_size = 1
        stalls = 0

        for _ in range(_MAX_STEP_ROUNDS):
            diff = target - current
            if diff == 0 or abs(diff) < step_size:
                break
            increase = diff > 0
            inverted = step_key in self._inverted_steps
            direction = (
                DIRECTION_INCREASE if increase != inverted else DIRECTION_DECREASE
            )
            count = max(1, min(abs(diff) // step_size, _MAX_STEP_BATCH))
            for _ in range(count):
                await self.write(step, prefix + bytes((direction,)))

            new = await self.read_value(query)
            if new is None:
                raise CommandDisabledError(f"{query} is not available")
            new = int(new)
            moved = new - current
            if moved == 0:
                stalls += 1
                if stalls >= 2:
                    # At a limit, or the projector ignores the command.
                    break
            elif (moved > 0) != increase:
                _LOGGER.debug("Step command %s moves %s the other way", step, query)
                self._inverted_steps ^= {step_key}
                stalls = 0
            else:
                step_size = max(1, abs(moved) // count)
                stalls = 0
            current = new
        return current

    async def probe(self) -> dict[str, ProbeResult]:
        """Read every documented query and report the raw outcome."""
        results: dict[str, ProbeResult] = {}
        for query, info in QUERIES.items():
            try:
                reply = await self.read(info.code)
            except ProjectorTimeoutError:
                results[query.value] = ProbeResult("timeout")
                continue
            if reply is None:
                results[query.value] = ProbeResult("disabled")
                continue
            value: int | float | None
            try:
                value = decode_value(query, reply)
            except ValueError:
                value = None
            results[query.value] = ProbeResult("ok", reply.data.hex(" "), value)
        return results
