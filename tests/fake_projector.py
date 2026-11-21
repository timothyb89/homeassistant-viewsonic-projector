"""A simulated ViewSonic projector, served over TCP.

serialx opens ``socket://host:port`` URLs like any serial port, so tests drive
the integration through the real transport stack.
"""

import asyncio
import contextlib

from custom_components.viewsonic_projector.protocol import (
    AUDIO_MODE,
    POWER_OFF,
    POWER_ON,
    QUERIES,
    RGB_GAIN,
    RGB_OFFSET,
    SPDIF_OFF,
    SPDIF_ON,
    VOLUME_DOWN,
    VOLUME_SET,
    VOLUME_UP,
    Code,
    PowerState,
    Query,
    checksum,
)

ACK = bytes.fromhex("03 14 00 00 00 14")
DISABLED = bytes.fromhex("00 14 00 00 00 14")

type Addr = tuple[int, int]


def addr(query: Query | Code) -> Addr:
    """Return the (cmd2, cmd3) tuple of a query or code."""
    code = QUERIES[query].code if isinstance(query, Query) else query
    return (code.cmd2, code.cmd3)


def read_response(data: bytes) -> bytes:
    """Encode a read response carrying ``data``."""
    payload = b"\x00\x00" + data
    body = bytes((0x14, 0x00)) + len(payload).to_bytes(2, "little") + payload
    return bytes((0x05,)) + body + bytes((checksum(body),))


# Values that can only be changed with increase/decrease commands.
STEP_QUERIES = (
    Query.BRIGHTNESS,
    Query.CONTRAST,
    Query.SHARPNESS,
    Query.HUE,
    Query.SATURATION,
    Query.GAIN,
    Query.KEYSTONE_VERTICAL,
    Query.KEYSTONE_HORIZONTAL,
    Query.HORIZONTAL_POSITION,
    Query.VERTICAL_POSITION,
    Query.LENS_SHIFT_VERTICAL,
    Query.LENS_SHIFT_HORIZONTAL,
)
RGB_READS = {
    (addr(RGB_GAIN), 0): addr(Query.RED_GAIN),
    (addr(RGB_GAIN), 1): addr(Query.GREEN_GAIN),
    (addr(RGB_GAIN), 2): addr(Query.BLUE_GAIN),
    (addr(RGB_OFFSET), 0): addr(Query.RED_OFFSET),
    (addr(RGB_OFFSET), 1): addr(Query.GREEN_OFFSET),
    (addr(RGB_OFFSET), 2): addr(Query.BLUE_OFFSET),
}
# Commands that are accepted but change no queryable value.
ACTIONS = {
    (0x11, 0x02),  # reset all settings
    (0x11, 0x2A),  # reset color settings
    (0x11, 0x34),  # power toggle
    (0x11, 0x35),  # home
    (0x11, 0x37),  # lens focus
    (0x12, 0x05),  # auto adjust
    (0x13, 0x31),  # aspect ratio cycle
    (0x13, 0x33),  # color mode cycle
    (0x13, 0x35),  # audio mode cycle
    (0x13, 0x36),  # light source mode cycle
    (0x02, 0x04),  # remote key
}


class FakeProjector:
    """Simulates an LX700-4K-like projector."""

    def __init__(self) -> None:
        """Initialize with the projector on and typical settings."""
        self.power = PowerState.ON
        self.warm_up = False  # power on goes to WARMING_UP instead of ON
        self.volume_max = 10
        self.values: dict[Addr, int] = {
            addr(Query.COLOR_MODE): 0x04,
            addr(Query.LIGHT_SOURCE_MODE): 0x00,
            addr(Query.ASPECT_RATIO): 0x00,
            addr(Query.COLOR_TEMPERATURE): 0x01,
            addr(Query.PROJECTOR_POSITION): 0x00,
            addr(Query.BLANK): 0,
            addr(Query.FREEZE): 0,
            addr(Query.HDMI_CEC): 1,
            addr(Query.QUICK_AUTO_SEARCH): 1,
            addr(Query.HIGH_ALTITUDE): 0,
            addr(Query.SPDIF): 1,
            addr(Query.AUDIO_MODE): 0x04,
            addr(Query.BRIGHTNESS): 0,
            addr(Query.CONTRAST): -10,
            addr(Query.SHARPNESS): 8,
            addr(Query.KEYSTONE_VERTICAL): 0,
            addr(Query.RED_GAIN): 50,
            addr(Query.BRILLIANT_COLOR): 5,
            addr(Query.INPUT_SOURCE): 0x03,
            addr(Query.VOLUME): 5,
            addr(Query.MUTE): 0,
            addr(Query.LIGHT_SOURCE_HOURS): 1234,
            addr(Query.EQUIVALENT_LIGHT_SOURCE_HOURS): 1000,
            addr(Query.OPERATING_TEMPERATURE): 297,
        }
        self.widths: dict[Addr, int] = {
            addr(Query.BRIGHTNESS): 2,
            addr(Query.CONTRAST): 2,
            addr(Query.SHARPNESS): 2,
            addr(Query.RED_GAIN): 2,
            addr(Query.LIGHT_SOURCE_HOURS): 4,
            addr(Query.EQUIVALENT_LIGHT_SOURCE_HOURS): 4,
            addr(Query.OPERATING_TEMPERATURE): 8,
        }
        self.limits: dict[Addr, tuple[int, int]] = {
            addr(Query.BRIGHTNESS): (-50, 50),
            addr(Query.CONTRAST): (-50, 50),
            addr(Query.SHARPNESS): (1, 15),
            addr(Query.KEYSTONE_VERTICAL): (-30, 30),
        }
        self.disabled: set[Addr] = set()  # answered with the "disabled" reply
        self.silent: set[Addr] = set()  # never answered
        self.delays: dict[Addr, float] = {}  # reply only after a delay
        # Stop answering anything after this many more requests.
        self.silent_after: int | None = None
        self.inverted_steps: set[Addr] = set()  # step commands that move backwards
        self.standby_readable: set[Addr] = {addr(Query.LIGHT_SOURCE_HOURS)}
        self.received: list[bytes] = []
        self.actions: list[tuple[Addr, bytes]] = []
        self.connections = 0
        self._server: asyncio.Server | None = None
        self._writers: set[asyncio.StreamWriter] = set()
        self.url = ""

    # -- Server ------------------------------------------------------------------

    async def start(self) -> str:
        """Start listening; return the socket:// URL."""
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        port = self._server.sockets[0].getsockname()[1]
        self.url = f"socket://127.0.0.1:{port}"
        return self.url

    async def stop(self) -> None:
        """Stop the server and drop clients."""
        await self.drop_connections()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def drop_connections(self) -> None:
        """Close every client connection (simulates a lost link)."""
        for writer in list(self._writers):
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
        self._writers.clear()

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self.connections += 1
        self._writers.add(writer)
        buffer = bytearray()
        try:
            while data := await reader.read(256):
                buffer += data
                while (packet := self._take_packet(buffer)) is not None:
                    reply = self.handle_packet(packet)
                    if (delay := self.delays.get(self._addr_of(packet))) is not None:
                        await asyncio.sleep(delay)
                    if reply is not None:
                        writer.write(reply)
                        await writer.drain()
        except ConnectionError:
            pass
        finally:
            self._writers.discard(writer)
            writer.close()

    @staticmethod
    def _take_packet(buffer: bytearray) -> bytes | None:
        while buffer and buffer[0] not in (0x06, 0x07):
            del buffer[0]
        if len(buffer) < 5:
            return None
        total = 5 + int.from_bytes(buffer[3:5], "little") + 1
        if len(buffer) < total:
            return None
        packet = bytes(buffer[:total])
        del buffer[:total]
        return packet

    @staticmethod
    def _addr_of(packet: bytes) -> Addr:
        payload = packet[5:-1]
        return (
            (payload[3], payload[4]) if packet[0] == 0x07 else (payload[1], payload[2])
        )

    # -- Protocol ------------------------------------------------------------------

    def handle_packet(self, packet: bytes) -> bytes | None:
        """Return the reply to a request packet."""
        self.received.append(packet)
        if self.silent_after is not None:
            if self.silent_after <= 0:
                return None
            self.silent_after -= 1
        assert packet[1:3] == b"\x14\x00", packet.hex(" ")
        assert checksum(packet[1:-1]) == packet[-1], packet.hex(" ")
        payload = packet[5:-1]
        assert payload[0] == 0x34, packet.hex(" ")
        if packet[0] == 0x07:
            assert payload[1:3] == b"\x00\x00", packet.hex(" ")
            return self._read((payload[3], payload[4]))
        return self._write((payload[1], payload[2]), payload[3:])

    def _read(self, code: Addr) -> bytes | None:
        if code in self.silent:
            return None
        if code == addr(Query.POWER):
            return read_response(bytes((self.power,)))
        if self.power is not PowerState.ON and code not in self.standby_readable:
            return DISABLED
        if code in self.disabled or code not in self.values:
            return DISABLED
        value = self.values[code]
        width = self.widths.get(code, 1)
        return read_response(value.to_bytes(width, "little", signed=value < 0))

    def _write(self, code: Addr, data: bytes) -> bytes | None:
        if code in self.silent:
            return None
        if code == addr(POWER_ON):
            if self.power is PowerState.OFF:
                self.power = PowerState.WARMING_UP if self.warm_up else PowerState.ON
            return ACK
        if code == addr(POWER_OFF):
            self.power = PowerState.OFF
            return ACK
        if self.power is not PowerState.ON or code in self.disabled:
            return DISABLED

        if code in {addr(q) for q in STEP_QUERIES} or code in (
            addr(RGB_GAIN),
            addr(RGB_OFFSET),
        ):
            target = RGB_READS.get((code, data[0]), code) if len(data) > 1 else code
            if target not in self.values:
                return DISABLED
            delta = 1 if data[-1] == 1 else -1
            if code in self.inverted_steps:
                delta = -delta
            low, high = self.limits.get(target, (-100, 100))
            self.values[target] = min(max(self.values[target] + delta, low), high)
            return ACK
        if code == addr(VOLUME_SET):
            self.values[addr(Query.VOLUME)] = min(data[0], self.volume_max)
            return ACK
        if code in (addr(VOLUME_UP), addr(VOLUME_DOWN)):
            delta = 1 if code == addr(VOLUME_UP) else -1
            volume = self.values[addr(Query.VOLUME)] + delta
            self.values[addr(Query.VOLUME)] = min(max(volume, 0), self.volume_max)
            self.values[addr(Query.MUTE)] = 0
            return ACK
        if code == addr(AUDIO_MODE):
            if data[0] in (SPDIF_ON, SPDIF_OFF):
                self.values[addr(Query.SPDIF)] = 0 if data[0] == SPDIF_ON else 1
            else:
                self.values[addr(Query.AUDIO_MODE)] = data[0]
            return ACK
        if code in ACTIONS:
            self.actions.append((code, data))
            return ACK
        if code in self.values:
            self.values[code] = data[0]
            return ACK
        return DISABLED

    # -- Helpers for assertions ------------------------------------------------------

    def value(self, query: Query) -> int:
        """Return the simulated value of a query."""
        return self.values[addr(query)]

    def set_value(self, query: Query, value: int) -> None:
        """Change a simulated value (as if changed on the projector itself)."""
        self.values[addr(query)] = value

    def writes(self) -> list[bytes]:
        """Return the write packets received so far."""
        return [packet for packet in self.received if packet[0] == 0x06]
