"""混音控制状态：每位乐手的分轨音量/静音与总音量/静音。

分轨静音用 send volume=0 实现（REAPER OSC 无 send mute），
因此记录静音前的电平以便恢复；总静音用母线 track mute 实现。
电平值均为 REAPER 归一化推子位 0..1（0=-inf，≈0.716=0dB，1=+12dB）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_SOURCE_LEVEL = 0.75
DEFAULT_MASTER_LEVEL = 0.75


@dataclass
class MixState:
    source_levels: list[float]
    source_muted: list[bool]
    _pre_mute_levels: list[float] = field(repr=False)
    master_level: float = DEFAULT_MASTER_LEVEL
    master_muted: bool = False

    @classmethod
    def create(cls, source_count: int) -> "MixState":
        return cls(
            source_levels=[DEFAULT_SOURCE_LEVEL] * source_count,
            source_muted=[False] * source_count,
            _pre_mute_levels=[DEFAULT_SOURCE_LEVEL] * source_count,
        )

    def set_source_level(self, index: int, value: float) -> dict:
        value = self._clamp(value)
        self.source_levels[index] = value
        if not self.source_muted[index]:
            self._pre_mute_levels[index] = value
        return {"type": "source_level", "index": index, "value": value}

    def set_source_mute(self, index: int, muted: bool) -> dict:
        self.source_muted[index] = muted
        return {"type": "source_mute", "index": index, "muted": muted}

    def set_master_level(self, value: float) -> dict:
        value = self._clamp(value)
        self.master_level = value
        return {"type": "master_level", "value": value}

    def set_master_mute(self, muted: bool) -> dict:
        self.master_muted = muted
        return {"type": "master_mute", "muted": muted}

    def send_level(self, index: int) -> float:
        """实际要发送到 REAPER 的 send 电平：静音时为 0，否则为滑块值。"""
        return 0.0 if self.source_muted[index] else self.source_levels[index]

    def resize(self, new_count: int) -> None:
        """源轨数量随 REAPER 工程动态变化时，保留重叠部分并补齐/截断。"""
        old = len(self.source_levels)
        if new_count == old:
            return
        if new_count > old:
            self.source_levels += [DEFAULT_SOURCE_LEVEL] * (new_count - old)
            self.source_muted += [False] * (new_count - old)
            self._pre_mute_levels += [DEFAULT_SOURCE_LEVEL] * (new_count - old)
        else:
            self.source_levels = self.source_levels[:new_count]
            self.source_muted = self.source_muted[:new_count]
            self._pre_mute_levels = self._pre_mute_levels[:new_count]

    def snapshot(self) -> dict:
        return {
            "type": "state",
            "sources": [
                {"index": i, "level": round(level, 4), "muted": muted}
                for i, (level, muted) in enumerate(zip(self.source_levels, self.source_muted))
            ],
            "master": {"level": round(self.master_level, 4), "muted": self.master_muted},
        }

    @staticmethod
    def _clamp(value: float) -> float:
        return max(0.0, min(1.0, float(value)))


class MixManager:
    """按监听母线轨道号（int）管理每位乐手的混音状态；源轨数量动态变化时自动 resize。"""

    def __init__(self) -> None:
        self._mixes: dict[int, MixState] = {}

    def get(self, bus_track_number: int, source_count: int) -> MixState:
        mix = self._mixes.get(bus_track_number)
        if mix is None:
            mix = MixState.create(source_count)
            self._mixes[bus_track_number] = mix
        else:
            mix.resize(source_count)
        return mix
