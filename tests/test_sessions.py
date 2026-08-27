from __future__ import annotations

import asyncio

import pytest

from app.core.sessions import SessionManager, session_key


def test_session_key() -> None:
    assert session_key("bot1", "g1", "u1") == "bot1:g1:u1"
    assert session_key("bot1", "", "u1") == "bot1:private:u1"


@pytest.mark.asyncio
async def test_session_pending_confirm_cancel() -> None:
    manager = SessionManager(ttl_seconds=60, max_sessions=10)
    session = manager.get("bot1", "g1", "u1")
    assert session is not None
    question = await session.ask("确认删除？")
    assert "确认删除" in question
    assert await session.confirm() is True
    assert await session.confirm() is False

    await session.ask("继续？")
    assert await session.cancel() is True
    assert await session.cancel() is False
    await session.clear()
    assert session.state == {}


@pytest.mark.asyncio
async def test_session_ttl_prune() -> None:
    manager = SessionManager(ttl_seconds=30, max_sessions=10)
    manager.get("b", "g", "u")
    assert manager.active_count() == 1
    pruned = manager.prune(now=1e12)
    assert pruned == 1
    assert manager.active_count() == 0


@pytest.mark.asyncio
async def test_session_capacity_eviction() -> None:
    manager = SessionManager(ttl_seconds=3600, max_sessions=2)
    first = manager.get("b", "g1", "u")
    manager.get("b", "g2", "u")
    await asyncio.sleep(0.01)
    manager.get("b", "g3", "u")
    assert first is not None
    assert manager.get("b", "g1", "u", create=False) is None
    assert manager.get("b", "g3", "u", create=False) is not None
