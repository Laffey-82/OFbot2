"""welcome 插件：新成员入群欢迎。"""

from __future__ import annotations

from app.core.events import MemberJoined
from app.core.plugin import PluginContext

_ctx: PluginContext | None = None


def setup(ctx: PluginContext) -> None:
    global _ctx
    _ctx = ctx


async def on_member_joined(event: MemberJoined) -> None:
    if not event.group_id:
        return
    template = _ctx.config.get(
        "welcome_text", "欢迎 {nickname} 加入本群！发送 /help 查看可用命令。"
    )
    text = str(template).replace("{nickname}", str(event.user_id))
    await _ctx.send_group(event.group_id, text)
