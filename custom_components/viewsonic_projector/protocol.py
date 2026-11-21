"""ViewSonic projector RS-232/LAN binary control protocol.

Implements the "Projector RS-232/LAN Control Protocol Specification V1.5". This
module has no Home Assistant dependencies.

Packet layout (all multi-byte lengths are little endian)::

    Write request   06 14 00 LL MM 34 cmd2 cmd3 data... checksum
    Read request    07 14 00 05 00 34 00 00 cmd2 cmd3 checksum
    Write ack       03 14 00 00 00 14
    Read response   05 14 00 LL MM 00 00 data... checksum
    Disabled        00 14 00 00 00 14   (function greyed out / not available now)

``LL MM`` counts the bytes from byte 5 up to (excluding) the checksum. The
checksum is the sum of every byte except the first one, modulo 256.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import IntEnum, StrEnum

BAUD_RATES: tuple[int, ...] = (2400, 4800, 9600, 14400, 19200, 38400, 115200)
DEFAULT_BAUD_RATE = 115200

_HEADER = 0x14
_PAYLOAD_PREFIX = 0x34
# Longest documented reply (error status) carries 22 bytes; leave headroom.
_MAX_PAYLOAD = 64


class PacketType(IntEnum):
    """First byte of a packet."""

    DISABLED = 0x00
    WRITE_ACK = 0x03
    READ_RESPONSE = 0x05
    WRITE = 0x06
    READ = 0x07


_REPLY_TYPES = frozenset(
    {PacketType.DISABLED, PacketType.WRITE_ACK, PacketType.READ_RESPONSE}
)


def checksum(data: Iterable[int]) -> int:
    """Return the protocol checksum of ``data`` (sum modulo 256)."""
    return sum(data) & 0xFF


def _packet(packet_type: int, payload: bytes) -> bytes:
    body = bytes((_HEADER, 0x00)) + len(payload).to_bytes(2, "little") + payload
    return bytes((packet_type,)) + body + bytes((checksum(body),))


def build_write(cmd2: int, cmd3: int, data: bytes | int = 0) -> bytes:
    """Build a write (set / execute) request."""
    if isinstance(data, int):
        data = bytes((data & 0xFF,))
    return _packet(PacketType.WRITE, bytes((_PAYLOAD_PREFIX, cmd2, cmd3)) + data)


def build_read(cmd2: int, cmd3: int) -> bytes:
    """Build a read (query) request."""
    return _packet(PacketType.READ, bytes((_PAYLOAD_PREFIX, 0x00, 0x00, cmd2, cmd3)))


@dataclass(frozen=True, slots=True)
class Reply:
    """A reply packet received from the projector."""

    type: PacketType
    payload: bytes

    @property
    def data(self) -> bytes:
        """Return the value bytes of a read response."""
        return self.payload[2:]

    def as_int(self, *, signed: bool = False) -> int:
        """Return the value of a read response as a little endian integer."""
        return int.from_bytes(self.data, "little", signed=signed)

    def raw(self) -> bytes:
        """Return the reply re-encoded as it appeared on the wire."""
        return _packet(self.type, self.payload)


class ReplyParser:
    """Incrementally split a byte stream into reply packets.

    Bytes that cannot start a valid packet (line noise, partial packets after a
    reconnect) are discarded one at a time until the stream re-synchronises.
    """

    def __init__(self) -> None:
        """Initialize the parser."""
        self._buffer = bytearray()
        self.discarded = 0

    def feed(self, data: bytes) -> list[Reply]:
        """Add received bytes and return every complete reply."""
        self._buffer += data
        replies: list[Reply] = []
        buf = self._buffer
        while len(buf) >= 6:
            if buf[0] not in _REPLY_TYPES or buf[1] != _HEADER or buf[2] != 0x00:
                del buf[0]
                self.discarded += 1
                continue
            length = int.from_bytes(buf[3:5], "little")
            if length > _MAX_PAYLOAD:
                del buf[0]
                self.discarded += 1
                continue
            total = 5 + length + 1
            if len(buf) < total:
                break
            if checksum(buf[1 : total - 1]) != buf[total - 1]:
                del buf[0]
                self.discarded += 1
                continue
            replies.append(Reply(PacketType(buf[0]), bytes(buf[5 : total - 1])))
            del buf[:total]
        return replies

    def reset(self) -> None:
        """Drop any buffered partial packet."""
        self._buffer.clear()


# ---------------------------------------------------------------------------
# Command catalogue
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Code:
    """A ``(cmd2, cmd3)`` command address."""

    cmd2: int
    cmd3: int

    def __str__(self) -> str:
        """Return the address formatted like the specification."""
        return f"0x{self.cmd2:02X} 0x{self.cmd3:02X}"


class PowerState(IntEnum):
    """Values returned by the power status query."""

    OFF = 0
    ON = 1
    WARMING_UP = 2
    COOLING_DOWN = 3


class Query(StrEnum):
    """Every documented read (query) command, keyed by a stable name."""

    POWER = "power"
    SPLASH_SCREEN = "splash_screen"
    QUICK_POWER_OFF = "quick_power_off"
    HIGH_ALTITUDE = "high_altitude"
    LIGHT_SOURCE_MODE = "light_source_mode"
    OSD_MESSAGES = "osd_messages"
    HDMI_FORMAT = "hdmi_format"
    HDMI_RANGE = "hdmi_range"
    HDMI_CEC = "hdmi_cec"
    EOTF = "eotf"
    FRAME_INTERPOLATION = "frame_interpolation"
    KEYSTONE_HORIZONTAL = "keystone_horizontal"
    SCREEN_COLOR = "screen_color"
    OVERSCAN = "overscan"
    PROJECTION_360 = "projection_360"
    SPDIF = "spdif"
    LENS_SHIFT_VERTICAL = "lens_shift_vertical"
    LENS_SHIFT_HORIZONTAL = "lens_shift_horizontal"
    PROJECTOR_POSITION = "projector_position"
    CONTRAST = "contrast"
    BRIGHTNESS = "brightness"
    ASPECT_RATIO = "aspect_ratio"
    HORIZONTAL_POSITION = "horizontal_position"
    VERTICAL_POSITION = "vertical_position"
    COLOR_TEMPERATURE = "color_temperature"
    BLANK = "blank"
    KEYSTONE_VERTICAL = "keystone_vertical"
    COLOR_MODE = "color_mode"
    SHARPNESS = "sharpness"
    BRILLIANT_COLOR = "brilliant_color"
    PRIMARY_COLOR = "primary_color"
    HUE = "hue"
    SATURATION = "saturation"
    GAIN = "gain"
    THREE_D_SYNC = "three_d_sync"
    THREE_D_SYNC_INVERT = "three_d_sync_invert"
    ISF_MODE = "isf_mode"
    HDR = "hdr"
    RED_GAIN = "red_gain"
    GREEN_GAIN = "green_gain"
    BLUE_GAIN = "blue_gain"
    RED_OFFSET = "red_offset"
    GREEN_OFFSET = "green_offset"
    BLUE_OFFSET = "blue_offset"
    FREEZE = "freeze"
    INPUT_SOURCE = "input_source"
    QUICK_AUTO_SEARCH = "quick_auto_search"
    MUTE = "mute"
    VOLUME = "volume"
    AUDIO_MODE = "audio_mode"
    LANGUAGE = "language"
    EQUIVALENT_LIGHT_SOURCE_HOURS = "equivalent_light_source_hours"
    LIGHT_SOURCE_HOURS = "light_source_hours"
    OPERATING_TEMPERATURE = "operating_temperature"
    REMOTE_CONTROL_CODE = "remote_control_code"
    GAMMA = "gamma"
    ERROR_STATUS = "error_status"


@dataclass(frozen=True, slots=True)
class QueryInfo:
    """How to read and decode a value."""

    code: Code
    signed: bool = False


QUERIES: dict[Query, QueryInfo] = {
    Query.POWER: QueryInfo(Code(0x11, 0x00)),
    Query.SPLASH_SCREEN: QueryInfo(Code(0x11, 0x0A)),
    Query.QUICK_POWER_OFF: QueryInfo(Code(0x11, 0x0B)),
    Query.HIGH_ALTITUDE: QueryInfo(Code(0x11, 0x0C)),
    Query.LIGHT_SOURCE_MODE: QueryInfo(Code(0x11, 0x10)),
    Query.OSD_MESSAGES: QueryInfo(Code(0x11, 0x27)),
    Query.HDMI_FORMAT: QueryInfo(Code(0x11, 0x28)),
    Query.HDMI_RANGE: QueryInfo(Code(0x11, 0x29)),
    Query.HDMI_CEC: QueryInfo(Code(0x11, 0x2B)),
    Query.EOTF: QueryInfo(Code(0x11, 0x2C)),
    Query.FRAME_INTERPOLATION: QueryInfo(Code(0x11, 0x2D)),
    Query.KEYSTONE_HORIZONTAL: QueryInfo(Code(0x11, 0x31), signed=True),
    Query.SCREEN_COLOR: QueryInfo(Code(0x11, 0x32)),
    Query.OVERSCAN: QueryInfo(Code(0x11, 0x33)),
    Query.PROJECTION_360: QueryInfo(Code(0x11, 0x36)),
    Query.SPDIF: QueryInfo(Code(0x11, 0x38)),
    Query.LENS_SHIFT_VERTICAL: QueryInfo(Code(0x11, 0x39), signed=True),
    Query.LENS_SHIFT_HORIZONTAL: QueryInfo(Code(0x11, 0x3A), signed=True),
    Query.PROJECTOR_POSITION: QueryInfo(Code(0x12, 0x00)),
    Query.CONTRAST: QueryInfo(Code(0x12, 0x02), signed=True),
    Query.BRIGHTNESS: QueryInfo(Code(0x12, 0x03), signed=True),
    Query.ASPECT_RATIO: QueryInfo(Code(0x12, 0x04)),
    Query.HORIZONTAL_POSITION: QueryInfo(Code(0x12, 0x06), signed=True),
    Query.VERTICAL_POSITION: QueryInfo(Code(0x12, 0x07), signed=True),
    Query.COLOR_TEMPERATURE: QueryInfo(Code(0x12, 0x08)),
    Query.BLANK: QueryInfo(Code(0x12, 0x09)),
    Query.KEYSTONE_VERTICAL: QueryInfo(Code(0x12, 0x0A), signed=True),
    Query.COLOR_MODE: QueryInfo(Code(0x12, 0x0B)),
    Query.SHARPNESS: QueryInfo(Code(0x12, 0x0E), signed=True),
    Query.BRILLIANT_COLOR: QueryInfo(Code(0x12, 0x0F)),
    Query.PRIMARY_COLOR: QueryInfo(Code(0x12, 0x10)),
    Query.HUE: QueryInfo(Code(0x12, 0x11), signed=True),
    Query.SATURATION: QueryInfo(Code(0x12, 0x12), signed=True),
    Query.GAIN: QueryInfo(Code(0x12, 0x13), signed=True),
    Query.THREE_D_SYNC: QueryInfo(Code(0x12, 0x20)),
    Query.THREE_D_SYNC_INVERT: QueryInfo(Code(0x12, 0x21)),
    Query.ISF_MODE: QueryInfo(Code(0x12, 0x38)),
    Query.HDR: QueryInfo(Code(0x12, 0x39)),
    Query.RED_GAIN: QueryInfo(Code(0x12, 0x3B), signed=True),
    Query.GREEN_GAIN: QueryInfo(Code(0x12, 0x3C), signed=True),
    Query.BLUE_GAIN: QueryInfo(Code(0x12, 0x3D), signed=True),
    Query.RED_OFFSET: QueryInfo(Code(0x12, 0x3F), signed=True),
    Query.GREEN_OFFSET: QueryInfo(Code(0x12, 0x40), signed=True),
    Query.BLUE_OFFSET: QueryInfo(Code(0x12, 0x41), signed=True),
    Query.FREEZE: QueryInfo(Code(0x13, 0x00)),
    Query.INPUT_SOURCE: QueryInfo(Code(0x13, 0x01)),
    Query.QUICK_AUTO_SEARCH: QueryInfo(Code(0x13, 0x02)),
    Query.MUTE: QueryInfo(Code(0x14, 0x00)),
    Query.VOLUME: QueryInfo(Code(0x14, 0x03)),
    Query.AUDIO_MODE: QueryInfo(Code(0x14, 0x05)),
    Query.LANGUAGE: QueryInfo(Code(0x15, 0x00)),
    Query.EQUIVALENT_LIGHT_SOURCE_HOURS: QueryInfo(Code(0x15, 0x01)),
    Query.LIGHT_SOURCE_HOURS: QueryInfo(Code(0x15, 0x0A)),
    Query.OPERATING_TEMPERATURE: QueryInfo(Code(0x15, 0x03)),
    Query.REMOTE_CONTROL_CODE: QueryInfo(Code(0x0C, 0x48)),
    Query.GAMMA: QueryInfo(Code(0x05, 0xCA)),
    Query.ERROR_STATUS: QueryInfo(Code(0x0C, 0x0D)),
}


def decode_value(query: Query, reply: Reply) -> int | float:
    """Decode a read response for ``query`` into a number."""
    if query is Query.OPERATING_TEMPERATURE:
        # Bytes 7-10 hold the temperature in tenths of a degree Celsius.
        return int.from_bytes(reply.data[:4], "little", signed=True) / 10
    if query in (
        Query.LIGHT_SOURCE_HOURS,
        Query.EQUIVALENT_LIGHT_SOURCE_HOURS,
    ):
        return int.from_bytes(reply.data[:4], "little")
    return reply.as_int(signed=QUERIES[query].signed)


# Write-only command addresses -------------------------------------------------

POWER_ON = Code(0x11, 0x00)
POWER_OFF = Code(0x11, 0x01)
POWER_TOGGLE = Code(0x11, 0x34)
RESET_ALL_SETTINGS = Code(0x11, 0x02)
RESET_COLOR_SETTINGS = Code(0x11, 0x2A)
HOME = Code(0x11, 0x35)
LENS_FOCUS = Code(0x11, 0x37)  # data 0 = left/near, 1 = right/far
AUTO_ADJUST = Code(0x12, 0x05)
RGB_GAIN = Code(0x12, 0x3A)  # data: channel (0 R, 1 G, 2 B), direction
RGB_OFFSET = Code(0x12, 0x3E)  # data: channel (0 R, 1 G, 2 B), direction
ASPECT_RATIO_CYCLE = Code(0x13, 0x31)
COLOR_MODE_CYCLE = Code(0x13, 0x33)
AUDIO_MODE_CYCLE = Code(0x13, 0x35)
LIGHT_SOURCE_MODE_CYCLE = Code(0x13, 0x36)
VOLUME_SET = Code(0x13, 0x2A)  # data = volume level
VOLUME_UP = Code(0x14, 0x01)
VOLUME_DOWN = Code(0x14, 0x02)
AUDIO_MODE = Code(0x14, 0x05)  # also carries the S/PDIF on (7) / off (8) values
RESET_LIGHT_SOURCE_HOURS = Code(0x15, 0x01)
REMOTE_KEY = Code(0x02, 0x04)  # data = key code

SPDIF_ON = 0x07
SPDIF_OFF = 0x08

DIRECTION_DECREASE = 0x00
DIRECTION_INCREASE = 0x01


# Enumerated values -------------------------------------------------------------

COLOR_MODES: dict[str, int] = {
    "brightest": 0x00,
    "movie": 0x01,
    "standard": 0x04,
    "srgb": 0x05,
    "dynamic": 0x08,
    "rec709": 0x09,
    "dicom_sim": 0x0A,
    "sports": 0x11,
    "gaming": 0x12,
    "photo": 0x13,
    "presentation": 0x14,
    "vivid": 0x15,
    "isf_day": 0x16,
    "isf_night": 0x17,
    "user_1": 0x18,
    "user_2": 0x19,
    "tv": 0x1A,
}

LIGHT_SOURCE_MODES: dict[str, int] = {
    "normal": 0x00,
    "eco": 0x01,
    "dynamic_eco": 0x02,
    "super_eco": 0x03,
    "custom_20": 0x04,
    "custom_40": 0x05,
    "custom_60": 0x06,
    "custom_80": 0x07,
    "custom_100": 0x08,
    "dynamic_black_1": 0x09,
    "dynamic_black_2": 0x0A,
}

PROJECTOR_POSITIONS: dict[str, int] = {
    "front_table": 0x00,
    "rear_table": 0x01,
    "rear_ceiling": 0x02,
    "front_ceiling": 0x03,
}

THREE_D_SYNC_MODES: dict[str, int] = {
    "off": 0x00,
    "auto": 0x01,
    "frame_sequential": 0x02,
    "frame_packing": 0x03,
    "top_bottom": 0x04,
    "side_by_side": 0x05,
}

ASPECT_RATIOS: dict[str, int] = {
    "auto": 0x00,
    "4_3": 0x02,
    "16_9": 0x03,
    "16_10": 0x04,
    "anamorphic": 0x05,
    "wide": 0x06,
    "2_35_1": 0x07,
    "panorama": 0x08,
    "native": 0x09,
    "16_6": 0x0A,
}

COLOR_TEMPERATURES: dict[str, int] = {
    "warm": 0x00,
    "normal": 0x01,
    "neutral": 0x02,
    "cool": 0x03,
    "9300k": 0x04,
    "9000k": 0x05,
    "user": 0x06,
}

PRIMARY_COLORS: dict[str, int] = {
    "red": 0x00,
    "green": 0x01,
    "blue": 0x02,
    "cyan": 0x03,
    "magenta": 0x04,
    "yellow": 0x05,
}

INPUT_SOURCES: dict[str, int] = {
    "computer_1": 0x00,
    "computer_2": 0x08,
    "hdmi_1": 0x03,
    "hdmi_2": 0x07,
    "hdmi_3": 0x09,
    "hdmi_4": 0x0E,
    "composite": 0x05,
    "s_video": 0x06,
    "dvi": 0x0A,
    "component": 0x0B,
    "hdbaset": 0x0C,
    "usb_c": 0x0F,
    "smart_system": 0x10,
    "usb_reader": 0x1A,
    "lan_display": 0x1B,
    "usb_display": 0x1C,
    "usb_2": 0x1E,
}

LANGUAGES: dict[str, int] = {
    "english": 0x00,
    "french": 0x01,
    "german": 0x02,
    "italian": 0x03,
    "spanish": 0x04,
    "russian": 0x05,
    "traditional_chinese": 0x06,
    "simplified_chinese": 0x07,
    "japanese": 0x08,
    "korean": 0x09,
    "swedish": 0x0A,
    "dutch": 0x0B,
    "turkish": 0x0C,
    "czech": 0x0D,
    "portuguese": 0x0E,
    "thai": 0x0F,
    "polish": 0x10,
    "finnish": 0x11,
    "arabic": 0x12,
    "indonesian": 0x13,
    "hindi": 0x14,
    "vietnamese": 0x15,
    "greek": 0x16,
    "hungarian": 0x17,
}

HDMI_FORMATS: dict[str, int] = {"rgb": 0x00, "yuv": 0x01, "auto": 0x02}
HDMI_RANGES: dict[str, int] = {"full": 0x00, "limited": 0x01, "auto": 0x02}
SCREEN_COLORS: dict[str, int] = {
    "off": 0x00,
    "blackboard": 0x01,
    "greenboard": 0x02,
    "whiteboard": 0x03,
    "blueboard": 0x04,
}
SPLASH_SCREENS: dict[str, int] = {
    "black": 0x00,
    "blue": 0x01,
    "viewsonic": 0x02,
    "screen_capture": 0x03,
    "off": 0x04,
}
EOTF_LEVELS: dict[str, int] = {"low": 0x00, "mid": 0x01, "high": 0x02}
FRAME_INTERPOLATION_LEVELS: dict[str, int] = {
    "low": 0x00,
    "mid": 0x01,
    "high": 0x02,
    "off": 0x03,
}
GAMMAS: dict[str, int] = {
    "1_8": 0x00,
    "2_0": 0x01,
    "2_2": 0x02,
    "2_35": 0x03,
    "2_5": 0x04,
    "srgb": 0x05,
    "cubic": 0x06,
}
HDR_MODES: dict[str, int] = {"auto": 0x00, "sdr": 0x01}
AUDIO_MODES: dict[str, int] = {
    "speech": 0x01,
    "movie": 0x04,
    "music": 0x05,
    "user": 0x06,
}
REMOTE_CONTROL_CODES: dict[str, int] = {f"code_{n}": n - 1 for n in range(1, 9)}

REMOTE_KEYS: dict[str, int] = {
    "source": 0x04,
    "auto": 0x08,
    "up": 0x0B,
    "down": 0x0C,
    "left": 0x0D,
    "right": 0x0E,
    "menu": 0x0F,
    "my_button": 0x11,
    "exit": 0x13,
    "enter": 0x15,
    "bluetooth": 0x26,
    "return": 0x27,
    "next_track": 0x28,
    "previous_track": 0x29,
    "play": 0x2A,
    "sub_menu": 0x2B,
}
