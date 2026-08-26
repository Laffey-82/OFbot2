from __future__ import annotations

from app.core.events import GroupMessageReceived
from app.core.messages import Message, MessageEvent
from app.core.plugin import Plugin, PluginContext
from app.services.preset_utils import JsonStore, preset_data_path


class StatsPlugin(Plugin):
    def setup(self, ctx: PluginContext) -> None:
        store = JsonStore(preset_data_path("stats"))

        async def on_message(event: GroupMessageReceived) -> None:
            data = await store.load()
            group = data.setdefault(event.group_id, {"messages": 0, "users": {}})
            group["messages"] += 1
            group["users"][event.user_id] = group["users"].get(event.user_id, 0) + 1
            await store.save()

        ctx.subscribe(GroupMessageReceived, on_message)

        @ctx.commands.command("stats", aliases={"统计"}, permission="stats.use", plugin_name=ctx.name)
        async def stats(event: MessageEvent, args: Message, command_ctx) -> None:
            data = await store.load()
            group_id = getattr(event, "group_id", "private")
            group = data.get(group_id)
            if group is None:
                await event.reply("暂无统计数据")
                return
            await event.reply(f"消息数：{group['messages']}\n活跃用户：{len(group['users'])}")


def create_plugin() -> Plugin:
    return StatsPlugin()
