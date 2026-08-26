from __future__ import annotations

from app.core.events import GroupMessageReceived
from app.core.plugin import Plugin, PluginContext


class AntiSpamPlugin(Plugin):
    def setup(self, ctx: PluginContext) -> None:
        limit = int(ctx.config.get("limit", 5))
        window = float(ctx.config.get("window", 10))

        async def on_message(event: GroupMessageReceived) -> None:
            key = f"spam:{event.group_id}:{event.user_id}"
            count = int(ctx.cache.get(key) or 0) + 1
            ctx.cache.set(key, count, ttl=window)
            if count == limit:
                await ctx.send_group(event.group_id, f"@{event.user_id} 发言过快，请慢一点")

        ctx.subscribe(GroupMessageReceived, on_message)


def create_plugin() -> Plugin:
    return AntiSpamPlugin()
