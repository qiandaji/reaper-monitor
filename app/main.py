"""reaper-monitor 服务入口：REST + 控制/音频 WebSocket + ReaStream UDP 中继。

监听轨道完全动态：REAPER 里名称以 monitor_prefix（默认 "MON "）开头的轨道
即监听母线，其余轨道为源轨；轨道名经 OSC 反馈自动发现，无需在配置里登记乐手。
"""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from .config import Settings, load_config
from .discovery import discover
from .osc_gateway import OscGateway
from .reastream import ReaStreamReceiver
from .state import MixManager
from .streams import StreamHub

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("reaper_monitor")

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.from_env(PROJECT_ROOT)
    try:
        config = load_config(settings.config_path)
    except Exception as exc:
        log.error("配置加载失败: %s", exc)
        raise

    gateway = OscGateway(settings.osc_reaper_host, settings.osc_reaper_port,
                         settings.osc_listen_host, settings.osc_listen_port)
    gateway.start()
    hub = StreamHub()
    mix_manager = MixManager()

    loop = asyncio.get_running_loop()
    receiver = ReaStreamReceiver(hub.on_block)
    transport, _ = await loop.create_datagram_endpoint(
        lambda: receiver,
        local_addr=(settings.reastream_host, settings.reastream_port),
    )

    app.state.settings = settings
    app.state.config = config
    app.state.gateway = gateway
    app.state.hub = hub
    app.state.mix_manager = mix_manager
    app.state.control_clients: dict[str, set[WebSocket]] = {}
    app.state.udp_transport = transport
    app.state.udp_receiver = receiver

    log.info("reaper-monitor 启动：HTTP/WS %s:%s，ReaStream UDP %s:%s，配置 %s",
             settings.http_host, settings.http_port, settings.reastream_host, settings.reastream_port, settings.config_path)
    try:
        yield
    finally:
        transport.close()
        gateway.shutdown()
        for subs in app.state.control_clients.values():
            for ws in list(subs):
                try:
                    asyncio.create_task(ws.close(code=1001))
                except Exception:
                    pass


app = FastAPI(title="reaper-monitor", lifespan=lifespan)


# ------------------------------------------------------------------ 工具

def _current_view() -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
    """按当前 OSC 轨道名快照计算 (监听母线列表, 源轨列表)，均按轨道号升序。"""
    gateway: OscGateway = app.state.gateway
    return discover(gateway.track_names, app.state.config.monitor_prefix)


def _monitor_name(bus_track_number: int) -> str | None:
    gateway: OscGateway = app.state.gateway
    name = gateway.track_names.get(bus_track_number)
    if name is None or not name.startswith(app.state.config.monitor_prefix):
        return None
    return name


# ------------------------------------------------------------------ REST

@app.get("/api/config")
async def api_config():
    monitors, sources = _current_view()
    return {
        "monitor_prefix": app.state.config.monitor_prefix,
        "monitors": [{"id": str(track_number), "name": name} for track_number, name in monitors],
        "sources": [name for _, name in sources],
    }


@app.get("/api/health")
async def api_health():
    monitors, sources = _current_view()
    return {
        "ok": True,
        "gateway": app.state.gateway.status(),
        "udp": {**app.state.udp_receiver.stats, "identifiers": app.state.udp_receiver.identifiers},
        "streams": {**app.state.hub.stats, "subscriber_streams": app.state.hub.subscriber_streams},
        "monitors": len(monitors),
        "sources": len(sources),
    }


# ------------------------------------------------------------------ 控制 WS

@app.websocket("/ws/control/{track_number}")
async def ws_control(ws: WebSocket, track_number: str):
    try:
        bus_track_number = int(track_number)
    except ValueError:
        await ws.close(code=4404, reason="invalid track number")
        return
    bus_name = _monitor_name(bus_track_number)
    if bus_name is None:
        await ws.close(code=4404, reason="unknown monitor track")
        return

    await ws.accept()
    musician_id = str(bus_track_number)
    mix = app.state.mix_manager.get(bus_track_number, len(_current_view()[1]))
    app.state.control_clients.setdefault(musician_id, set()).add(ws)
    try:
        await ws.send_text(json.dumps(mix.snapshot(), ensure_ascii=False))
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_text(json.dumps({"type": "error", "message": "无效的 JSON 命令"}, ensure_ascii=False))
                continue
            try:
                await _handle_control_command(ws, musician_id, bus_track_number, bus_name, msg)
            except Exception as exc:
                log.warning("控制命令处理失败: %s", exc)
                await _send_error(ws, f"命令处理失败: {exc}")
    except WebSocketDisconnect:
        pass
    except Exception:
        log.warning("控制 WS 异常断开", exc_info=True)
    finally:
        clients = app.state.control_clients.get(musician_id)
        if clients is not None:
            clients.discard(ws)
            if not clients:
                app.state.control_clients.pop(musician_id, None)


async def _handle_control_command(ws: WebSocket, musician_id: str, bus_track_number: int, bus_name: str, msg: dict) -> None:
    gateway: OscGateway = app.state.gateway
    _, sources = _current_view()
    source_count = len(sources)
    mix = app.state.mix_manager.get(bus_track_number, source_count)
    cmd = msg.get("type")

    if cmd in ("set_source_level", "set_source_mute"):
        index = int(msg["index"])
        if not 0 <= index < source_count:
            await _send_error(ws, f"源轨序号 {index} 超出范围（当前共 {source_count} 条源轨）")
            return
        source_track_number, source_name = sources[index]
        send_index = gateway.resolve_send_index(source_track_number, bus_name)
        if send_index is None:
            await _send_error(
                ws,
                f"源轨「{source_name}」上没有到「{bus_name}」的 send，"
                f"请在 REAPER 中创建该 send 并确认其名称与监听母线轨道名一致",
            )
            return
        if cmd == "set_source_level":
            mix.set_source_level(index, float(msg["value"]))
        else:
            mix.set_source_mute(index, bool(msg["muted"]))
        gateway.send_source_level(source_track_number, send_index, mix.send_level(index))

    elif cmd == "set_master_level":
        mix.set_master_level(float(msg["value"]))
        gateway.set_bus_volume(bus_track_number, mix.master_level)

    elif cmd == "set_master_mute":
        mix.set_master_mute(bool(msg["muted"]))
        gateway.set_bus_mute(bus_track_number, mix.master_muted)

    else:
        await _send_error(ws, f"未知命令: {cmd}")
        return

    snapshot = json.dumps(mix.snapshot(), ensure_ascii=False)
    for client in list(app.state.control_clients.get(musician_id, ())):
        try:
            await client.send_text(snapshot)
        except Exception:
            pass


async def _send_error(ws: WebSocket, message: str) -> None:
    try:
        await ws.send_text(json.dumps({"type": "error", "message": message}, ensure_ascii=False))
    except Exception:
        pass


# ------------------------------------------------------------------ 音频 WS

@app.websocket("/ws/audio/{track_number}")
async def ws_audio(ws: WebSocket, track_number: str):
    try:
        bus_track_number = int(track_number)
    except ValueError:
        await ws.close(code=4404, reason="invalid track number")
        return
    bus_name = _monitor_name(bus_track_number)
    if bus_name is None:
        await ws.close(code=4404, reason="unknown monitor track")
        return

    await ws.accept()
    hub: StreamHub = app.state.hub
    sub: object | None = None
    try:
        # ReaStream identifier 约定 = 监听母线轨道名（完全一致）。
        sub = hub.add_subscriber(bus_name, ws)
        while True:
            await ws.receive_text()  # 客户端不发数据；收到任何文本即忽略，断开则抛异常
    except WebSocketDisconnect:
        pass
    except Exception:
        log.debug("音频 WS 断开", exc_info=True)
    finally:
        if sub is not None:
            sub.close()


# ------------------------------------------------------------------ 静态页面（挂在最后，兜底路由）

app.mount("/", StaticFiles(directory=str(PROJECT_ROOT / "app" / "static"), html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    settings = Settings.from_env(PROJECT_ROOT)
    uvicorn.run("app.main:app", host=settings.http_host, port=settings.http_port, reload=False)
