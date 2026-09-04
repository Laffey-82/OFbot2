"""四个已确认缺陷的行为回归测试。

覆盖：background.submit 同名去重、重连循环代际退出、退避重置、
mirai session 失效重认证、qq_official 坏 JSON 容错、red 非数值字段容错、
manager 覆盖任务前取消旧任务。
"""

from __future__ import annotations

import asyncio
import json
import time

import httpx
import pytest

from app.adapters.base import BaseAdapter, BotClient
from app.adapters.manager import ConnectionManager
from app.adapters.mirai import MiraiAdapter
from app.adapters.qq_official import OfficialQQAdapter
from app.adapters.red import RedAdapter
from app.core.background import BackgroundWorker
from app.core.config import ConnectionSettings, RedSettings
from app.core.messages import GroupMessageEvent


class RecordingClient(BotClient):
    def __init__(self) -> None:
        super().__init__()
        self.events: list = []

    async def handle_bot_event(self, event):
        self.events.append(event)
        return True


class FakeAdapter(BaseAdapter):
    async def start(self) -> None:
        await self.run_reconnect_loop(self._connect, self.bot_id)

    async def _connect(self) -> None:
        raise NotImplementedError

    async def stop(self) -> None:
        self._running = False

    async def send_group_message(self, group_id, message) -> bool:
        return True

    async def send_private_message(self, user_id, message) -> bool:
        return True


def _fake_adapter(**overrides) -> FakeAdapter:
    params: dict = {"reconnect_interval": 0.05}
    params.update(overrides)
    settings = ConnectionSettings(**params)
    return FakeAdapter(settings, BotClient())


async def _cleanup_bus() -> None:
    from app.core.bus import get_bus, reset_bus

    try:
        await get_bus().stop(clear=True)
    except Exception:
        pass
    await reset_bus()


@pytest.mark.asyncio
async def test_background_submit_dedupes_running_task() -> None:
    worker = BackgroundWorker(queue_size=10, workers=1)
    started = asyncio.Event()
    release = asyncio.Event()
    runs: list[str] = []

    async def first() -> None:
        runs.append("first")
        started.set()
        await release.wait()

    async def duplicate() -> None:
        runs.append("duplicate")

    await worker.start()
    await worker.submit("dup", first())
    await started.wait()
    existing = await worker.submit("dup", duplicate())
    assert existing is not None and not existing.done()
    release.set()
    await worker.queue.join()
    await worker.stop()
    assert runs == ["first"]


@pytest.mark.asyncio
async def test_background_submit_allows_same_name_in_queue() -> None:
    """队列中同名但不同协程的任务不会被去重（各自独立执行）。"""
    worker = BackgroundWorker(queue_size=10, workers=1)
    runs: list[str] = []

    async def job() -> None:
        runs.append("job")

    async def duplicate() -> None:
        runs.append("duplicate")

    await worker.submit("bench", job())
    await worker.submit("bench", duplicate())
    assert worker.queue.qsize() == 2
    await worker.start()
    await worker.queue.join()
    await worker.stop()
    assert sorted(runs) == ["duplicate", "job"]


@pytest.mark.asyncio
async def test_stale_reconnect_loop_exits_after_new_start() -> None:
    """旧 run_reconnect_loop 在退避等待中被新 start 取代后必须退出。"""
    adapter = _fake_adapter(reconnect_interval=0.15, reconnect_max_seconds=10.0)
    attempts: list[float] = []

    async def connect() -> None:
        attempts.append(time.monotonic())
        raise ConnectionError("boom")

    old = asyncio.create_task(adapter.run_reconnect_loop(connect, "fake"))
    while not attempts:
        await asyncio.sleep(0.01)
    # 旧循环此刻已失败一次并进入退避 sleep；模拟新 start() 取代它
    new = asyncio.create_task(adapter.run_reconnect_loop(connect, "fake"))
    await asyncio.sleep(0.6)
    assert old.done()
    assert old.exception() is None
    new.cancel()
    try:
        await new
    except (asyncio.CancelledError, Exception):
        pass


@pytest.mark.asyncio
async def test_backoff_resets_after_stable_connection() -> None:
    """连接曾稳定保持超过阈值后断开：退避 attempt 归零，延迟回到第一档。"""
    adapter = _fake_adapter(reconnect_interval=0.4, reconnect_max_seconds=10.0)
    stamps: list[float] = []

    async def connect() -> None:
        stamps.append(time.monotonic())
        if len(stamps) == 2:
            # 模拟第二次连接曾稳定保持 >60s 后断开
            adapter._connected_since = time.monotonic() - 61.0
        raise ConnectionError("boom")

    task = asyncio.create_task(adapter.run_reconnect_loop(connect, "fake"))
    await asyncio.sleep(1.8)
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass
    assert len(stamps) >= 3
    gap1 = stamps[1] - stamps[0]
    gap2 = stamps[2] - stamps[1]
    # 重置生效：gap2 回到第一档（≈0.32~0.48s）；未重置时应为 0.64~0.96s
    assert gap2 < 0.6, (gap1, gap2)


def _mirai_adapter(handler) -> MiraiAdapter:
    adapter = MiraiAdapter(
        ConnectionSettings(protocol="mirai", api_base="http://m"), "m", BotClient()
    )
    adapter._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return adapter


@pytest.mark.asyncio
async def test_mirai_reauthenticates_on_invalid_session_code() -> None:
    sessions: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/verify":
            sessions.append(f"s{len(sessions)}")
            return httpx.Response(200, json={"code": 0, "session": sessions[-1]})
        if path == "/bind":
            return httpx.Response(200, json={"code": 0})
        if path == "/fetchMessage":
            key = request.url.params.get("sessionKey")
            if key == "s0":
                return httpx.Response(200, json={"code": 3})
            return httpx.Response(200, json={"code": 0, "data": []})
        return httpx.Response(404)

    adapter = _mirai_adapter(handler)
    try:
        await adapter._ensure_session()
        assert adapter._session_key == "s0"
        await adapter._poll_once()
        assert adapter._session_key == "s1"
    finally:
        await adapter._http.aclose()


@pytest.mark.asyncio
async def test_mirai_raises_after_repeated_reauth_failures() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/verify":
            return httpx.Response(200, json={"code": 2, "message": "bad key"})
        return httpx.Response(200, json={"code": 4})

    adapter = _mirai_adapter(handler)
    adapter._session_key = "stale"
    try:
        await adapter._poll_once()
        await adapter._poll_once()
        assert adapter._reauth_failures == 2
        with pytest.raises(RuntimeError, match="重新认证"):
            await adapter._poll_once()
    finally:
        await adapter._http.aclose()


@pytest.mark.asyncio
async def test_qq_official_malformed_frame_does_not_trigger_reconnect() -> None:
    from app.core.bus import get_bus, reset_bus

    adapter = OfficialQQAdapter(
        ConnectionSettings(id="qq", protocol="qq_official", app_id="1", token="t"),
        "qq",
        BotClient(),
    )
    try:
        # malformed 帧应被跳过（不抛异常打断 recv_loop），好帧仍正常处理
        await adapter._handle_raw_frame("{not-json")
        await adapter._handle_raw_frame("")
        await adapter._handle_raw_frame(
            json.dumps({"op": 10, "d": {"heartbeat_interval": 30000}})
        )
        assert adapter._heartbeat_task is not None
    finally:
        await adapter.stop()
        try:
            await get_bus().stop(clear=True)
        except Exception:
            pass
        await reset_bus()


@pytest.mark.asyncio
async def test_red_tolerates_non_numeric_payload_fields() -> None:
    from app.core.bus import get_bus, reset_bus
    from app.core.events import NoticeReceived

    client = RecordingClient()
    adapter = RedAdapter(RedSettings(), "red", client)
    noticed: list = []
    bus = get_bus()
    bus.on(NoticeReceived, lambda event: noticed.append(event))
    try:
        # chatType 非数值 → 按默认群聊（2）处理，不打断收包循环
        await adapter._handle_message(
            {
                "msgId": "m1",
                "chatType": "not-a-number",
                "senderUin": "100",
                "peerUin": "200",
                "elements": [
                    {"elementType": 1, "textElement": {"content": "hi"}}
                ],
            }
        )
        assert client.events and isinstance(client.events[0], GroupMessageEvent)
        assert client.events[0].group_id == "200"

        # fileSize 非数值 → 默认 0
        adapter._dispatch_notice({"noticeType": "unknown", "fileSize": "12MB"})
        await bus.wait_until_idle()
        assert noticed and noticed[0].file_size == 0
    finally:
        await get_bus().stop(clear=True)
        await reset_bus()


@pytest.mark.asyncio
async def test_manager_cancels_superseded_task_before_override() -> None:
    class HangingAdapter:
        bot_id = "bot"

        async def start(self) -> None:
            await asyncio.Event().wait()

    manager = ConnectionManager()
    manager.adopt([HangingAdapter()])
    first = manager.start_connection("bot")
    second = manager.start_connection("bot")
    assert first is not None and second is not None
    await asyncio.sleep(0.05)
    assert first.cancelled()
    assert not second.done()
    second.cancel()
    await asyncio.gather(first, second, return_exceptions=True)
