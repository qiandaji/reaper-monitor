"""ReaStream UDP 接收与解析。

协议（1014.org/shiz/reastream.txt，经 wireshark dissector 与 libReaStream 交叉验证）：
UDP 默认端口 58710，全小端。每个音频包：
  0..3    4B  魔数 'M','R','S','R' (0x4D 0x52 0x53 0x52)
  4..7    int32 packetSize（= 整个数据报长度，含魔数本身：4+4+32+1+4+2+sblocklen）
  8..39   32B  identifier（零填充）
  40      1B   声道数 nch（1..64）
  41..44  int32 采样率
  45..46  int16 sblocklen（≤1200；更大的块会被拆成多个 UDP 包）
  47..    样本数据：32bit float，非交错（planar）排列
单包完整约束：sblocklen % (nch*4) == 0 的包才是一个完整块；
本项目 README 要求 REAPER 音频设备块大小 ≤128（立体声）以保证单包完整。

接收端按 identifier 缓存字节流，从第一个完整包推导块大小（帧数）后按完整块
交付给订阅方，从而兼容偶发的多包拆分。
"""
from __future__ import annotations

import asyncio
import logging
import struct
import time
from dataclasses import dataclass

log = logging.getLogger("reaper_monitor.reastream")

MAGIC = b"MRSR"
HEADER_SIZE = 47  # 4(魔数) + 4(packetSize) + 32(identifier) + 1(nch) + 4(采样率) + 2(sblocklen)
MAX_PENDING_BYTES = 1 << 18  # 尚未推导出块大小时的单流缓存上限


@dataclass(frozen=True)
class ReaStreamPacket:
    identifier: str
    channels: int
    sample_rate: int
    sblocklen: int
    payload: bytes  # planar f32


def parse_packet(data: bytes) -> ReaStreamPacket | None:
    """解析一个 ReaStream UDP 数据报；不合法返回 None。"""
    if len(data) < HEADER_SIZE or data[:4] != MAGIC:
        return None
    packet_size = struct.unpack_from("<i", data, 4)[0]
    # packetSize 含魔数本身、等于整个数据报长度；只取声明的长度，容忍尾部字节
    if packet_size < HEADER_SIZE or packet_size > len(data):
        return None
    data = data[:packet_size]
    identifier = data[8:40].split(b"\x00", 1)[0].decode("utf-8", "replace").strip()
    channels = data[40]
    if not 1 <= channels <= 64:
        return None
    sample_rate = struct.unpack_from("<i", data, 41)[0]
    if sample_rate <= 0:
        return None
    sblocklen = struct.unpack_from("<H", data, 45)[0]
    payload = data[47 : 47 + sblocklen]
    if len(payload) != sblocklen:
        return None
    return ReaStreamPacket(identifier, channels, sample_rate, sblocklen, payload)


BlockCallback = object  # 占位：实际为 callable(identifier, channels, sample_rate, frames, block: bytes)


class ReaStreamReceiver(asyncio.DatagramProtocol):
    """UDP 接收器：解析数据报、按 identifier 重组完整音频块并回调。"""

    def __init__(self, on_block) -> None:
        self.on_block = on_block
        self.transport: asyncio.DatagramTransport | None = None
        self._pending: dict[str, bytearray] = {}
        self._block_frames: dict[str, int] = {}
        self._last_warn = 0.0
        self.stats = {"packets": 0, "bytes": 0, "blocks": 0, "malformed": 0, "streams": 0, "dropped": 0}

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr) -> None:
        self.stats["packets"] += 1
        self.stats["bytes"] += len(data)
        pkt = parse_packet(data)
        if pkt is None:
            self.stats["malformed"] += 1
            self._warn_once(
                f"丢弃无法解析的 UDP 包（len={len(data)}，来源 {addr}）。"
                "请确认 REAPER 里每个监听母线上的 ReaStream destination 指向本机 ReaStream 端口。"
            )
            return
        if pkt.identifier not in self._pending:
            self.stats["streams"] = len(self._pending) + 1
        buf = self._pending.setdefault(pkt.identifier, bytearray())
        buf += pkt.payload
        frames = self._block_frames.get(pkt.identifier)
        if frames is None and pkt.sblocklen > 0 and pkt.sblocklen % (pkt.channels * 4) == 0:
            frames = pkt.sblocklen // (pkt.channels * 4)
            self._block_frames[pkt.identifier] = frames
            log.info("stream %s: nch=%d sample_rate=%d block_frames=%d",
                     pkt.identifier, pkt.channels, pkt.sample_rate, frames)
        if frames is None:
            if len(buf) > MAX_PENDING_BYTES:
                buf.clear()
                self.stats["dropped"] += 1
                self._warn_once(
                    f"stream {pkt.identifier} 缓冲超过 {MAX_PENDING_BYTES} 字节仍未出现完整块。"
                    "请确认 REAPER 音频设备块大小（立体声建议 ≤128，单声道 ≤300）。"
                )
            return
        block_bytes = frames * pkt.channels * 4
        while len(buf) >= block_bytes:
            block = bytes(buf[:block_bytes])
            del buf[:block_bytes]
            self.stats["blocks"] += 1
            self.on_block(pkt.identifier, pkt.channels, pkt.sample_rate, frames, block)

    @property
    def identifiers(self) -> list[str]:
        """已收到过数据包的 ReaStream identifier 列表（用于排查流名不匹配）。"""
        return sorted(self._pending.keys())

    def _warn_once(self, message: str) -> None:
        now = time.monotonic()
        if now - self._last_warn >= 5.0:
            self._last_warn = now
            log.warning(message)
