from __future__ import annotations

from app.core.messages import Message, MessageEvent
from app.core.plugin import Plugin, PluginContext


class AnnouncementPlugin(Plugin):
    def setup(self, ctx: PluginContext) -> None:
        groups = [str(g) for g in ctx.config.get("groups", [])]

        @ctx.commands.command("announce", permission="announcement.send", plugin_name=ctx.name)
        async def announce(event: MessageEvent, args: Message, command_ctx) -> None:
            text = args.extract_plain_text().strip()
            if not text:
                await event.reply("用法：/announce 公告内容")
                return
            for group_id in groups:
                await ctx.send_group(group_id, text)
            await event.reply("公告已发送")


def create_plugin() -> Plugin:
    return AnnouncementPlugin()
