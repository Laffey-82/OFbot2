"""announcement 插件：向配置的群发送公告。"""

from __future__ import annotations

from app.core.messages import Message, MessageEvent
from app.core.plugin import PluginContext

_ctx: PluginContext | None = None


def setup(ctx: PluginContext) -> None:
    global _ctx
    _ctx = ctx


async def announce_command(
    event: MessageEvent, args: Message, command_ctx
) -> None:
    params = getattr(command_ctx, "params", None) or {}
    content = str(params.get("content", "")).strip()
    group_id = str(_ctx.config.get("group_id", "") or "").strip()
    if not content:
        await event.reply("公告内容为空")
        return
    if not group_id:
        await event.reply("未配置公告目标群（插件配置 group_id）")
        return
    await _ctx.send_group(group_id, f"📢 公告：{content}")
    await event.reply("公告已发送")
