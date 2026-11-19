"""混音状态测试。"""
from __future__ import annotations

from app.state import MixManager, MixState


def test_defaults():
    mix = MixState.create(3)
    assert mix.source_levels == [0.75, 0.75, 0.75]
    assert mix.source_muted == [False, False, False]
    assert mix.master_level == 0.75
    assert mix.master_muted is False


def test_set_source_level_clamps():
    mix = MixState.create(1)
    mix.set_source_level(0, 1.5)
    assert mix.source_levels[0] == 1.0
    mix.set_source_level(0, -0.2)
    assert mix.source_levels[0] == 0.0


def test_mute_restores_pre_mute_level():
    mix = MixState.create(1)
    mix.set_source_level(0, 0.4)
    mix.set_source_mute(0, True)
    assert mix.send_level(0) == 0.0
    mix.set_source_level(0, 0.6)  # 静音中拖动滑块
    assert mix.send_level(0) == 0.0
    mix.set_source_mute(0, False)
    assert mix.send_level(0) == 0.6


def test_master_mute_flag():
    mix = MixState.create(1)
    mix.set_master_mute(True)
    assert mix.master_muted is True
    assert mix.snapshot()["master"]["muted"] is True


def test_mix_manager_singleton_per_track():
    manager = MixManager()
    assert manager.get(3, 4) is manager.get(3, 4)
    assert manager.get(3, 4) is not manager.get(5, 4)


def test_mix_manager_resizes_on_source_count_change():
    manager = MixManager()
    mix = manager.get(3, 2)
    mix.set_source_level(0, 0.4)
    mix.set_source_level(1, 0.6)
    manager.get(3, 4)  # 源轨从 2 变 4：保留前两个，补齐默认值
    assert mix.source_levels == [0.4, 0.6, 0.75, 0.75]
    manager.get(3, 1)  # 源轨从 4 变 1：截断
    assert mix.source_levels == [0.4]
