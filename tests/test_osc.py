"""OSC 网关出站命令与轨道名/send 名反馈解析测试（不打网络）。"""
from __future__ import annotations

import pytest

from app import osc_gateway as mod


class StubClient:
    def __init__(self):
        self.sent = []

    def send_message(self, address, value):
        self.sent.append((address, value))


@pytest.fixture()
def gateway(monkeypatch):
    stub = StubClient()
    monkeypatch.setattr(mod, "SimpleUDPClient", lambda host, port: stub)
    gw = mod.OscGateway("127.0.0.1", 9212, "0.0.0.0", 9213)
    gw._client = stub
    return gw, stub


def test_send_source_level(gateway):
    gw, stub = gateway
    gw.send_source_level(3, 2, 0.5)
    assert stub.sent[-1] == ("/track/3/send/2/volume", 0.5)


def test_bus_volume_and_mute(gateway):
    gw, stub = gateway
    gw.set_bus_volume(7, 0.8)
    gw.set_bus_mute(7, True)
    assert stub.sent[-2] == ("/track/7/volume", 0.8)
    assert stub.sent[-1] == ("/track/7/mute", 1)


def test_track_name_feedback_resolves_number(gateway):
    gw, _ = gateway
    gw._on_track_name("/track/5/name", ["name"], "MON 鼓手")
    assert gw.resolve_track_number("MON 鼓手") == 5


def test_send_name_feedback_and_resolution(gateway):
    gw, _ = gateway
    gw._on_send_name("/track/3/send/2/name", ["name"], "MON 鼓手")
    assert gw.resolve_send_index(3, "MON 鼓手") == 2
    assert gw.resolve_send_index(3, "MON 贝斯") is None
    assert gw.resolve_send_index(9, "MON 鼓手") is None


def test_send_name_address_does_not_corrupt_track_names(gateway):
    # 回归：python-osc 1.10.3 的 /track/*/name 会跨段误匹配 /track/1/send/1/name
    gw, _ = gateway
    gw._on_track_name("/track/1/send/1/name", ["name"], "MON 鼓手")
    assert gw.track_names == {}
    gw._on_send_name("/track/1/name", ["name"], "MON 鼓手")
    assert gw._send_names == {}
