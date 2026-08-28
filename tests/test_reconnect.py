from __future__ import annotations

import asyncio

import pytest

from app.adapters.base import BaseAdapter, BotClient
from app.core.config import ConnectionSettings


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


def _adapter(**overrides) -> FakeAdapter:
    params = {"reconnect_interval": 0.05}
    params.update(overrides)
    settings = ConnectionSettings(**params)
    return FakeAdapter(settings, BotClient())


@pytest.mark.asyncio
async def test_reconnect_backoff_increases_delay() -> None:
    # 基础间隔 0.3s（抖动 0.8~1.2 后第一档 0.24~0.36、第二档 0.48~0.72，
    # 两档区间不重叠），避免 0.1s 下限把两档压成相等导致时序抖动误报。
    adapter = _adapter(reconnect_interval=0.3, reconnect_max_seconds=1.0)
    attempts_meta = []

    async def connect() -> None:
        attempts_meta.append(asyncio.get_event_loop().time())
        if len(attempts_meta) < 3:
            raise ConnectionError("boom")
        await asyncio.Event().wait()

    task = asyncio.create_task(adapter.run_reconnect_loop(connect, "fake"))
    await asyncio.sleep(1.5)
    assert len(attempts_meta) >= 3
    gaps = [
        attempts_meta[i + 1] - attempts_meta[i]
        for i in range(len(attempts_meta) - 1)
    ]
    # 基础 0.05s 指数退避：首个间隔 ~0.04-0.06，第二个 ~0.08-0.12
    assert gaps[0] < gaps[1]
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass


@pytest.mark.asyncio
async def test_reconnect_max_attempts_disables() -> None:
    adapter = _adapter(reconnect_max_attempts=2)

    async def connect() -> None:
        raise ConnectionError("always fails")

    task = asyncio.create_task(adapter.run_reconnect_loop(connect, "fake"))
    await asyncio.sleep(0.5)
    assert adapter.bot_client.status["fake"] == "disabled"
    assert adapter._running is False
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass


@pytest.mark.asyncio
async def test_recv_loop_heartbeat_stale() -> None:
    adapter = _adapter()

    class FakeWs:
        async def recv(self) -> str:
            await asyncio.sleep(60)
            return ""

    with pytest.raises(ConnectionError, match="heartbeat stale"):
        await adapter.recv_loop(FakeWs(), lambda raw: None, "fake", stale_seconds=0.05)
