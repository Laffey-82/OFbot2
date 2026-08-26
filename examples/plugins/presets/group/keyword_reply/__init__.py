from __future__ import annotations

from app.core.events import GroupMessageReceived
from app.core.plugin import Plugin, PluginContext


class KeywordReplyPlugin(Plugin):
    def setup(self, ctx: PluginContext) -> None:
        rules = ctx.config.get("rules", {})

        async def on_message(event: GroupMessageReceived) -> None:
            for keyword, reply in rules.items():
                if keyword and keyword in event.message:
                    await ctx.send_group(event.group_id, reply)
                    return

        ctx.subscribe(GroupMessageReceived, on_message)


def create_plugin() -> Plugin:
    return KeywordReplyPlugin()
