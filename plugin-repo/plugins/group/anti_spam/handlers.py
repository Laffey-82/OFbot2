"""anti_spam 插件处理器：窗口内刷屏提醒。"""

from __future__ import annotations

from app.core.events import GroupMessageReceived
from app.core.plugin import PluginContext

_ctx: PluginContext | None = None


def setup(ctx: PluginContext) -> None:
    global _ctx
    _ctx = ctx


async def on_group_message(event: GroupMessageReceived) -> None:
    limit = int(_ctx.config.get("limit", 5))
    window = float(_ctx.config.get("window", 10))
    key = f"spam:{event.group_id}:{event.user_id}"
    count = int(_ctx.cache.get(key) or 0) + 1
    _ctx.cache.set(key, count, ttl=window)
    if count == limit:
        await _ctx.send_group(
            event.group_id, f"@{event.user_id} 发言过快，请慢一点"
        )
