"""timestamp 插件处理器：时间戳 ↔ 日期。"""

from __future__ import annotations

from datetime import datetime

from app.core.messages import Message, MessageEvent
from app.core.plugin import PluginContext

_ctx: PluginContext | None = None


def setup(ctx: PluginContext) -> None:
    global _ctx
    _ctx = ctx


async def timestamp_command(
    event: MessageEvent, args: Message, command_ctx
) -> None:
    value = args.extract_plain_text().strip()
    try:
        if value.isdigit():
            dt = datetime.fromtimestamp(int(value))
            await event.reply(dt.strftime("%Y-%m-%d %H:%M:%S"))
        else:
            dt = datetime.fromisoformat(value)
            await event.reply(str(int(dt.timestamp())))
    except Exception:
        await event.reply("用法：/timestamp <时间戳或YYYY-MM-DD HH:MM:SS>")
