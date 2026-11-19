"""ReaStream 音频扇出：按 stream_id 把音频块分发给每位乐手的 WebSocket。

每个订阅者一条发送队列（有界，满时丢最旧块——实时监听宁可丢旧帧也不堆积延迟），
独立 worker 串行发送，保证 WebSocket 帧顺序。
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

log = logging.getLogger("reaper_monitor.streams")

QUEUE_SIZE = 64  # 每订阅者音频块队列上限（块大小 ≤128 帧 ≈ 3ms，64 块 ≈ 200ms 缓冲）


class StreamHub:
    def __init__(self) -> None:
        self._subscribers: dict[str, set["_Subscriber"]] = {}
        self._stream_meta: dict[str, dict[str, int]] = {}
        self.stats = {"blocks_received": 0, "blocks_forwarded": 0, "dropped_no_subscriber": 0, "subscribers": 0}

    def add_subscriber(self, stream_id: str, websocket: Any) -> "_Subscriber":
        stream_id = stream_id.strip()
        sub = _Subscriber(stream_id, websocket, self._on_subscriber_done)
        self._subscribers.setdefault(stream_id, set()).add(sub)
        self.stats["subscribers"] = sum(len(s) for s in self._subscribers.values())
        meta = self._stream_meta.get(stream_id)
        if meta is not None:
            sub.enqueue_text(json.dumps({"type": "stream_info", **meta}))
        return sub

    def _on_subscriber_done(self, sub: "_Subscriber") -> None:
        subs = self._subscribers.get(sub.stream_id)
        if subs is None:
            return
        subs.discard(sub)
        if not subs:
            self._subscribers.pop(sub.stream_id, None)
        self.stats["subscribers"] = sum(len(s) for s in self._subscribers.values())

    def on_block(self, identifier: str, channels: int, sample_rate: int, frames: int, block: bytes) -> None:
        identifier = identifier.strip()
        self.stats["blocks_received"] += 1
        subs = self._subscribers.get(identifier)
        if not subs:
            self.stats["dropped_no_subscriber"] += 1
            return
        meta = self._stream_meta.get(identifier)
        if meta is None:
            meta = {"channels": channels, "sampleRate": sample_rate, "framesPerBlock": frames}
            self._stream_meta[identifier] = meta
            info = json.dumps({"type": "stream_info", **meta})
            for sub in list(subs):
                sub.enqueue_text(info)
        for sub in list(subs):
            sub.enqueue_bytes(block)
            self.stats["blocks_forwarded"] += 1


    @property
    def subscriber_streams(self) -> list[str]:
        """当前有订阅者的 stream_id 列表（用于排查流名不匹配）。"""
        return sorted(self._subscribers.keys())


class _Subscriber:
    def __init__(self, stream_id: str, websocket: Any, on_done) -> None:
        self.stream_id = stream_id
        self.websocket = websocket
        self._on_done = on_done
        self._queue: asyncio.Queue[tuple[str, object] | None] = asyncio.Queue(maxsize=QUEUE_SIZE)
        self._task = asyncio.create_task(self._run())

    def enqueue_text(self, text: str) -> None:
        self._put(("text", text))

    def enqueue_bytes(self, data: bytes) -> None:
        self._put(("bytes", data))

    def _put(self, item: tuple[str, object]) -> None:
        if self._queue.full():
            # 丢最旧，保持低延迟
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            self._queue.put_nowait(item)
        except asyncio.QueueFull:
            pass

    async def _run(self) -> None:
        try:
            while True:
                item = await self._queue.get()
                if item is None:
                    return
                kind, payload = item
                if kind == "text":
                    await self.websocket.send_text(str(payload))
                else:
                    await self.websocket.send_bytes(payload)
        except Exception:
            log.debug("音频订阅者断开", exc_info=True)
        finally:
            self._on_done(self)

    def close(self) -> None:
        try:
            self._queue.put_nowait(None)
        except asyncio.QueueFull:
            pass
