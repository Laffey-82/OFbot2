"""插件状态持久化：加载/卸载/失败状态与最近错误。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.db.base import session_factory
from app.db.models import PluginState


async def save_plugin_state(
    name: str,
    state: str,
    *,
    error: str = "",
    version: str = "",
) -> None:
    """记录插件状态与最近错误（error 截断至 2000 字符）。"""
    async with session_factory()() as session:
        row = await session.get(PluginState, name)
        if row is None:
            session.add(
                PluginState(
                    name=name,
                    state=state,
                    error=error[:2000],
                    version=version[:32],
                )
            )
        else:
            row.state = state
            row.error = error[:2000]
            if version:
                row.version = version[:32]
        await session.commit()


async def get_plugin_states() -> dict[str, dict[str, Any]]:
    """返回 {插件名: {"state": ..., "error": ...}}。"""
    async with session_factory()() as session:
        rows = (await session.scalars(select(PluginState))).all()
    return {
        row.name: {"state": row.state, "error": row.error}
        for row in rows
    }
