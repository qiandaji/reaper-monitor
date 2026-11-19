"""从 REAPER 轨道名动态发现监听母线与源轨。

约定：
- 名称以 monitor_prefix 开头的轨道 = 监听母线（每位乐手一条，轨道号 = 乐手 id）。
- 其余轨道 = 源轨，按轨道号升序排列（网页分轨顺序即此顺序）。
- 监听母线上的 ReaStream identifier 必须与轨道名完全一致；
  源轨 send 的名称必须与目标监听母线轨道名一致（REAPER 新建 send 默认即如此）。
"""
from __future__ import annotations


def discover(track_names: dict[int, str], monitor_prefix: str) -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
    monitors = sorted(
        ((n, name) for n, name in track_names.items() if name.startswith(monitor_prefix)),
        key=lambda item: item[0],
    )
    monitor_numbers = {n for n, _ in monitors}
    sources = sorted(
        ((n, name) for n, name in track_names.items() if n not in monitor_numbers),
        key=lambda item: item[0],
    )
    return monitors, sources
