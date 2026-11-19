"""ReaStream 解析与接收器重组测试。"""
from __future__ import annotations

import struct

from app.reastream import MAGIC, ReaStreamReceiver, parse_packet


def build_datagram(identifier: str, channels: int, sample_rate: int, payload: bytes) -> bytes:
    ident = (identifier.encode("utf-8") + bytes(32))[:32]
    sblocklen = len(payload)
    packet_size = 4 + 4 + 32 + 1 + 4 + 2 + sblocklen  # 含魔数本身，等于整个数据报长度
    return MAGIC + struct.pack("<i", packet_size) + ident + bytes([channels]) + struct.pack("<i", sample_rate) + struct.pack("<H", sblocklen) + payload


def test_parse_valid_stereo_packet():
    payload = bytes(range(64))  # 8 帧立体声（8*2*4=64 字节）
    pkt = parse_packet(build_datagram("mon-drummer", 2, 48000, payload))
    assert pkt is not None
    assert pkt.identifier == "mon-drummer"
    assert pkt.channels == 2
    assert pkt.sample_rate == 48000
    assert pkt.sblocklen == 64
    assert pkt.payload == payload


def test_parse_rejects_bad_magic():
    data = bytearray(build_datagram("x", 2, 48000, b"1234"))
    data[0] = ord("X")
    assert parse_packet(bytes(data)) is None


def test_parse_rejects_truncated():
    data = build_datagram("x", 2, 48000, b"12345678")
    assert parse_packet(data[:20]) is None


def test_parse_rejects_bad_channels():
    data = bytearray(build_datagram("x", 2, 48000, b"1234"))
    data[40] = 0
    assert parse_packet(bytes(data)) is None


def test_parse_tolerates_trailing_bytes():
    data = build_datagram("x", 1, 44100, b"abcd") + b"trailing"
    pkt = parse_packet(data)
    assert pkt is not None and pkt.payload == b"abcd"


class _Collector:
    def __init__(self):
        self.blocks = []

    def __call__(self, identifier, channels, sample_rate, frames, block):
        self.blocks.append((identifier, channels, sample_rate, frames, block))


def test_receiver_reassembles_partial_blocks():
    collector = _Collector()
    receiver = ReaStreamReceiver(collector)
    # 完整块：立体声 2 帧 = 16 字节 payload，让接收器学会 block_frames=2
    receiver.datagram_received(build_datagram("s1", 2, 48000, bytes(16)), ("127.0.0.1", 1))
    assert len(collector.blocks) == 1
    assert collector.blocks[0][3] == 2
    # 后续两个各 1 帧（8 字节）的半块应缓存并拼成一个完整块
    receiver.datagram_received(build_datagram("s1", 2, 48000, bytes(range(8))), ("127.0.0.1", 1))
    assert len(collector.blocks) == 1
    receiver.datagram_received(build_datagram("s1", 2, 48000, bytes(range(8, 16))), ("127.0.0.1", 1))
    assert len(collector.blocks) == 2
    _, _, _, frames, block = collector.blocks[1]
    assert frames == 2
    assert block == bytes(range(16))


def test_receiver_drops_unparseable_and_counts():
    collector = _Collector()
    receiver = ReaStreamReceiver(collector)
    receiver.datagram_received(b"garbage", ("127.0.0.1", 1))
    assert receiver.stats["malformed"] == 1
    assert collector.blocks == []
