from __future__ import annotations

from datetime import datetime

from app.core.messages import Message, MessageEvent
from app.core.plugin import Plugin, PluginContext


class TimestampPlugin(Plugin):
    def setup(self, ctx: PluginContext) -> None:
        @ctx.commands.command("timestamp", aliases={"时间戳"}, permission="timestamp.use", plugin_name=ctx.name)
        async def timestamp(event: MessageEvent, args: Message, command_ctx) -> None:
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


def create_plugin() -> Plugin:
    return TimestampPlugin()
