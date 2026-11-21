"""Tests for the protocol encoder/decoder, using examples from the specification."""

import pytest

from custom_components.viewsonic_projector.protocol import (
    COLOR_MODES,
    GAMMAS,
    POWER_ON,
    QUERIES,
    RGB_GAIN,
    PacketType,
    Query,
    Reply,
    ReplyParser,
    build_read,
    build_write,
    checksum,
    decode_value,
)


def h(text: str) -> bytes:
    """Parse spec-style hex, e.g. '0x06 0x14'."""
    return bytes(int(token, 16) for token in text.split())


@pytest.mark.parametrize(
    ("packet", "expected"),
    [
        # 1 Power ON
        (build_write(POWER_ON.cmd2, POWER_ON.cmd3), "06 14 00 04 00 34 11 00 00 5D"),
        # 4 Power read status
        (build_read(0x11, 0x00), "07 14 00 05 00 34 00 00 11 00 5E"),
        # 109 Color mode Brightest
        (
            build_write(0x12, 0x0B, COLOR_MODES["brightest"]),
            "06 14 00 04 00 34 12 0B 00 69",
        ),
        # 116 Color mode Sports
        (
            build_write(0x12, 0x0B, COLOR_MODES["sports"]),
            "06 14 00 04 00 34 12 0B 11 7A",
        ),
        # 82 Color temperature red gain decrease (two data bytes)
        (
            build_write(RGB_GAIN.cmd2, RGB_GAIN.cmd3, bytes((0x00, 0x00))),
            "06 14 00 05 00 34 12 3A 00 00 99",
        ),
        # 295 Gamma 1.8 (checksum wraps around)
        (build_write(0x05, 0xCA, GAMMAS["1_8"]), "06 14 00 04 00 34 05 CA 00 1B"),
        # Factory mode 1: reset to factory default (no data byte)
        (build_write(0x0C, 0x08, b""), "06 14 00 03 00 34 0C 08 5F"),
        # 183 Volume write value
        (build_write(0x13, 0x2A, 0x11), "06 14 00 04 00 34 13 2A 11 9A"),
        # 212 Light source usage time
        (build_read(0x15, 0x0A), "07 14 00 05 00 34 00 00 15 0A 6C"),
    ],
)
def test_packets_match_specification(packet: bytes, expected: str) -> None:
    """Built packets are byte-identical to the specification."""
    assert packet == bytes.fromhex(expected)


def test_negative_write_value_is_twos_complement() -> None:
    """Negative data bytes are sent as two's complement."""
    assert build_write(0x13, 0x2A, -1)[-2] == 0xFF


def test_checksum() -> None:
    """The checksum is the byte sum modulo 256."""
    assert checksum(h("0x14 0x00 0x03 0x00 0x00 0x00 0x01")) == 0x18
    assert checksum([0xFF, 0x02]) == 0x01


def test_parser_handles_all_reply_types() -> None:
    """Write ACK, read response and disabled replies are recognised."""
    parser = ReplyParser()
    replies = parser.feed(
        h("0x03 0x14 0x00 0x00 0x00 0x14")
        + h("0x05 0x14 0x00 0x03 0x00 0x00 0x00 0x01 0x18")
        + h("0x00 0x14 0x00 0x00 0x00 0x14")
    )
    assert [reply.type for reply in replies] == [
        PacketType.WRITE_ACK,
        PacketType.READ_RESPONSE,
        PacketType.DISABLED,
    ]
    assert replies[1].as_int() == 1


def test_parser_reassembles_split_packets() -> None:
    """Replies split across reads are reassembled."""
    parser = ReplyParser()
    data = h("0x05 0x14 0x00 0x04 0x00 0x00 0x00 0x32 0x00 0x4A")
    assert parser.feed(data[:3]) == []
    assert parser.feed(data[3:7]) == []
    (reply,) = parser.feed(data[7:])
    assert reply.as_int(signed=True) == 50


def test_parser_skips_noise_and_bad_checksums() -> None:
    """Garbage and corrupted packets are dropped until the stream resyncs."""
    parser = ReplyParser()
    corrupt = h("0x05 0x14 0x00 0x03 0x00 0x00 0x00 0x01 0x19")
    good = h("0x05 0x14 0x00 0x03 0x00 0x00 0x00 0x02 0x19")
    replies = parser.feed(b"\xff\x13\x00" + corrupt + b"\x14" + good)
    assert len(replies) == 1
    assert replies[0].as_int() == 2
    assert parser.discarded > 0


@pytest.mark.parametrize(
    ("data", "signed", "expected"),
    [
        ("0x18 0xFF", True, -232),  # 3.2.2 two-byte table
        ("0xE7 0x00", True, 231),
        ("0xFF", True, -1),  # 3.2.1 one-byte table
        ("0xFF", False, 255),
    ],
)
def test_value_decoding(data: str, signed: bool, expected: int) -> None:
    """Values decode per the read response mapping tables."""
    reply = Reply(PacketType.READ_RESPONSE, b"\x00\x00" + h(data))
    assert reply.as_int(signed=signed) == expected


def test_decode_temperature_and_hours() -> None:
    """Notes 1 and 4: temperature in tenths of a degree, hours as uint32."""
    temperature = Reply(
        PacketType.READ_RESPONSE,
        h("0x00 0x00 0x29 0x01 0x00 0x00 0x00 0x00 0x00 0x00"),
    )
    assert decode_value(Query.OPERATING_TEMPERATURE, temperature) == 29.7
    hours = Reply(PacketType.READ_RESPONSE, h("0x00 0x00 0xB8 0x0B 0x00 0x00"))
    assert decode_value(Query.LIGHT_SOURCE_HOURS, hours) == 3000


def test_signed_settings_decode_negative() -> None:
    """Settings flagged as signed decode negative values."""
    reply = Reply(PacketType.READ_RESPONSE, h("0x00 0x00 0xCE 0xFF"))
    assert QUERIES[Query.BRIGHTNESS].signed
    assert decode_value(Query.BRIGHTNESS, reply) == -50
