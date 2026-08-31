from __future__ import annotations

import asyncio

import pytest

from app.core.bus import BaseEvent, EventBus, get_bus, reset_bus


class _BaseNotice(BaseEvent):
    group_id: str = ""


class _GroupPoke(_BaseNotice):
    target: str = ""


@pytest.mark.asyncio
async def test_dispatch_matches_exact_and_parent_class() -> None:
    """父类订阅可收到子类事件（GroupPoke → NoticeReceived 语义）。"""
    bus = EventBus(name="t-bus", max_history_size=100)
    received: list[BaseEvent] = []

    bus.on(_BaseNotice, lambda e: received.append(e))
    bus.on(_GroupPoke, lambda e: received.append(e))

    bus.dispatch(_GroupPoke(group_id="1", target="2"))
    await bus.stop(timeout=1.0)
    assert len(received) == 2
    assert all(isinstance(e, _GroupPoke) for e in received)


@pytest.mark.asyncio
async def test_handler_exception_does_not_break_others() -> None:
    bus = EventBus(name="t-bus", max_history_size=100)
    results: list[str] = []

    async def bad(_: BaseEvent) -> None:
        raise RuntimeError("boom")

    def good(_: BaseEvent) -> None:
        results.append("ok")

    bus.on(_BaseNotice, bad)
    bus.on(_BaseNotice, good)
    bus.dispatch(_GroupPoke(group_id="1"))
    await bus.stop(timeout=1.0)
    assert results == ["ok"]


@pytest.mark.asyncio
async def test_history_bounded() -> None:
    bus = EventBus(name="t-bus", max_history_size=3)
    for i in range(10):
        bus.dispatch(_BaseNotice(group_id=str(i)))
    assert len(bus._history) == 3  # type: ignore[attr-defined]
    assert bus._history[-1].group_id == "9"  # type: ignore[attr-defined]
    await bus.stop(clear=True)
    assert len(bus._history) == 0  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_stop_drains_pending_events() -> None:
    """高 pending 下 stop() 优雅排空，不阻塞事件循环。"""
    bus = EventBus(name="t-bus", max_history_size=500)
    done = asyncio.Event()
    counter = {"n": 0}

    async def slow(_: BaseEvent) -> None:
        await asyncio.sleep(0.001)
        counter["n"] += 1
        if counter["n"] == 200:
            done.set()

    bus.on(_BaseNotice, slow)
    for _ in range(200):
        bus.dispatch(_BaseNotice(group_id="1"))
    await asyncio.wait_for(bus.stop(timeout=5.0), timeout=6.0)
    assert counter["n"] == 200
    assert bus.pending_count == 0
    assert done.is_set()


@pytest.mark.asyncio
async def test_stop_timeout_cancels_slow_handlers() -> None:
    bus = EventBus(name="t-bus", max_history_size=500)
    cancelled = {"n": 0}

    async def forever(_: BaseEvent) -> None:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelled["n"] += 1
            raise

    bus.on(_BaseNotice, forever)
    for _ in range(10):
        bus.dispatch(_BaseNotice(group_id="1"))
    await asyncio.wait_for(bus.stop(timeout=0.1), timeout=2.0)
    assert cancelled["n"] == 10
    assert bus.pending_count == 0


@pytest.mark.asyncio
async def test_reset_bus_replaces_singleton_and_stops_old() -> None:
    old = get_bus()
    old.on(_BaseNotice, lambda e: None)
    await reset_bus()
    new = get_bus()
    assert new is not old
    assert new.pending_count == 0
    await reset_bus()
