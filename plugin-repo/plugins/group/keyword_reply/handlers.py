"""keyword_reply 插件：按配置的关键词规则自动回复。"""

from __future__ import annotations

from app.core.events import GroupMessageReceived
from app.core.plugin import PluginContext

_ctx: PluginContext | None = None


def setup(ctx: PluginContext) -> None:
    global _ctx
    _ctx = ctx


async def on_group_message(event: GroupMessageReceived) -> None:
    text = (event.message or "").strip()
    if not text:
        return
    for rule in _ctx.config.get("rules", []):
        keyword = str(rule.get("keyword", ""))
        reply = str(rule.get("reply", ""))
        if keyword and reply and keyword in text:
            await _ctx.send_group(event.group_id, reply)
            return
