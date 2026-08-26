"""schedule_message 插件：定时向指定群发送消息。"""

from __future__ import annotations

from app.core.plugin import PluginContext

_ctx: PluginContext | None = None


def setup(ctx: PluginContext) -> None:
    global _ctx
    _ctx = ctx


async def broadcast() -> None:
    group_id = str(_ctx.config.get("group_id", "") or "").strip()
    message = str(_ctx.config.get("message", "") or "").strip()
    if group_id and message:
        await _ctx.send_group(group_id, message)
