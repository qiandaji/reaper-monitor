"""OSC 网关：REAPER 内置 OSC 控制面的双向桥接。

出站（桥接 → REAPER）：
  /track/{源轨号}/send/{send序号}/volume  归一化推子位 0..1（分轨响度/静音）
  /track/{母线轨号}/volume               归一化推子位 0..1（总音量）
  /track/{母线轨号}/mute                 1/0（总静音）
  /device/track/follows/device + /device/track/count 心跳；/action 41743 请求刷新。
入站（REAPER → 桥接）：/track/@/name 用于把 data/config.json 里的轨道名解析成轨道号。

实现约定沿用 reaper-web-control（已验证）：BlockingOSCUDPServer + daemon 线程，
启动即发握手/刷新；每 2s 心跳，每 10 次心跳补一次刷新以捕捉晚启动的 REAPER。
"""
from __future__ import annotations

import logging
import threading
from typing import Any

from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import BlockingOSCUDPServer
from pythonosc.udp_client import SimpleUDPClient

log = logging.getLogger("reaper_monitor.osc")

HEARTBEAT_ADDRESS = "/device/track/follows/device"
DEVICE_TRACK_COUNT = 64
REFRESH_ALL_SURFACES_ACTION = 41743


class OscGateway:
    def __init__(self, reaper_host: str, reaper_port: int, listen_host: str, listen_port: int) -> None:
        self.reaper_host = reaper_host
        self.reaper_port = reaper_port
        self.listen_host = listen_host
        self.listen_port = listen_port
        self._client = SimpleUDPClient(reaper_host, reaper_port)
        self._server: BlockingOSCUDPServer | None = None
        self._server_thread: threading.Thread | None = None
        self._heartbeat_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._started = False
        self.last_error: str | None = None
        self._track_names: dict[int, str] = {}
        self._name_to_track: dict[str, int] = {}
        self._send_names: dict[int, dict[int, str]] = {}

    # ------------------------------------------------------------------ 生命周期

    def start(self) -> None:
        if self._started:
            return
        self._stop_event.clear()
        self.last_error = None
        try:
            self._server = BlockingOSCUDPServer((self.listen_host, self.listen_port), self._build_dispatcher())
            self._server_thread = threading.Thread(target=self._server.serve_forever, daemon=True)
            self._server_thread.start()
            self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
            self._heartbeat_thread.start()
            self._started = True
            self._request_refresh()
            log.info("OSC 监听 %s:%s（→ REAPER %s:%s）", self.listen_host, self.listen_port, self.reaper_host, self.reaper_port)
        except Exception as exc:
            self.last_error = str(exc)
            log.warning("OSC 网关启动失败: %s", exc)

    def shutdown(self) -> None:
        self._stop_event.set()
        if self._server is not None:
            try:
                self._server.shutdown()
            except Exception:
                pass
            try:
                self._server.server_close()
            except Exception:
                pass
            self._server = None
        self._started = False

    @property
    def track_names(self) -> dict[int, str]:
        """REAPER 反馈的轨道号 → 轨道名快照（只读）。"""
        return dict(self._track_names)

    def status(self) -> dict[str, Any]:
        return {
            "listening": self._started,
            "listen_host": self.listen_host,
            "listen_port": self.listen_port,
            "reaper_host": self.reaper_host,
            "reaper_port": self.reaper_port,
            "track_names": dict(self._track_names),
            "send_name_count": sum(len(v) for v in self._send_names.values()),
            "last_error": self.last_error,
        }

    # ------------------------------------------------------------------ 出站命令

    def send_source_level(self, source_track_number: int, send_index: int, value: float) -> None:
        """send_index 从 1 起（REAPER 里源轨的第 N 个 send）。value 为归一化推子位 0..1。"""
        self._send(f"/track/{source_track_number}/send/{send_index}/volume", float(value))

    def set_bus_volume(self, bus_track_number: int, value: float) -> None:
        self._send(f"/track/{bus_track_number}/volume", float(value))

    def set_bus_mute(self, bus_track_number: int, muted: bool) -> None:
        self._send(f"/track/{bus_track_number}/mute", 1 if muted else 0)

    def resolve_track_number(self, name: str) -> int | None:
        """把轨道名解析成 REAPER 轨道号（1 起）；未解析返回 None。"""
        return self._name_to_track.get(name)

    def resolve_send_index(self, source_track_number: int, bus_name: str) -> int | None:
        """在源轨的 send 里找名称等于监听母线轨道名的 send（1 起）；未解析返回 None。"""
        sends = self._send_names.get(source_track_number)
        if not sends:
            return None
        for send_index in sorted(sends):
            if sends[send_index] == bus_name:
                return send_index
        return None

    # ------------------------------------------------------------------ 内部

    def _send(self, address: str, value: Any) -> None:
        try:
            self._client.send_message(address, value)
        except Exception as exc:
            self.last_error = str(exc)
            log.warning("OSC 发送 %s 失败: %s", address, exc)

    def _build_dispatcher(self) -> Dispatcher:
        dispatcher = Dispatcher()
        dispatcher.map("/track/*/name", self._on_track_name, "name")
        dispatcher.map("/track/*/send/*/name", self._on_send_name, "name")
        return dispatcher

    def _send_handshake(self) -> None:
        self._send(HEARTBEAT_ADDRESS, "DEVICE")
        self._send("/device/track/count", DEVICE_TRACK_COUNT)

    def _request_refresh(self) -> None:
        self._send_handshake()
        self._send("/action", REFRESH_ALL_SURFACES_ACTION)

    def _heartbeat_loop(self) -> None:
        tick = 0
        while not self._stop_event.wait(2.0):
            tick += 1
            self._send_handshake()
            if tick % 10 == 0:
                self._request_refresh()

    # ------------------------------------------------------------------ 入站反馈

    @staticmethod
    def _osc_arg(args: tuple, default: Any = None) -> Any:
        return args[0] if args else default

    def _on_track_name(self, address: str, params: Any, *args) -> None:
        # python-osc 的通配符匹配会跨 "/" 段，/track/1/send/1/name 也会命中
        # /track/*/name，必须按段数精确把关。
        parts = address.split("/")
        if len(parts) != 4 or parts[1] != "track" or parts[3] != "name":
            return
        value = self._osc_arg(args)
        if value is None:
            return
        track_number = int(parts[2])
        name = str(value)
        self._track_names[track_number] = name
        self._name_to_track[name] = track_number

    def _on_send_name(self, address: str, params: Any, *args) -> None:
        parts = address.split("/")
        # /track/{轨道号}/send/{send序号}/name
        if len(parts) != 6 or parts[1] != "track" or parts[3] != "send" or parts[5] != "name":
            return
        value = self._osc_arg(args)
        if value is None:
            return
        track_number = int(parts[2])
        send_index = int(parts[4])
        self._send_names.setdefault(track_number, {})[send_index] = str(value)
