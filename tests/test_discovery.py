"""动态发现监听母线与源轨的测试。"""
from __future__ import annotations

from app.discovery import discover


def test_discovers_monitors_by_prefix_and_rest_as_sources():
    names = {
        1: "鼓",
        2: "贝斯",
        3: "MON 鼓手",
        4: "人声",
        5: "MON 主唱",
    }
    monitors, sources = discover(names, "MON ")
    assert monitors == [(3, "MON 鼓手"), (5, "MON 主唱")]
    assert sources == [(1, "鼓"), (2, "贝斯"), (4, "人声")]


def test_empty_when_no_monitors():
    names = {1: "鼓", 2: "贝斯"}
    monitors, sources = discover(names, "MON ")
    assert monitors == []
    assert sources == [(1, "鼓"), (2, "贝斯")]


def test_sorted_by_track_number():
    names = {9: "MON 甲", 2: "MON 乙", 7: "吉他"}
    monitors, sources = discover(names, "MON ")
    assert monitors == [(2, "MON 乙"), (9, "MON 甲")]
    assert sources == [(7, "吉他")]
