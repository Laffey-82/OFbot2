from __future__ import annotations

from app.core.messages import Message, MessageEvent
from app.core.plugin import Plugin, PluginContext
from app.services.preset_utils import JsonStore, preset_data_path


class PointsPlugin(Plugin):
    def setup(self, ctx: PluginContext) -> None:
        store = JsonStore(preset_data_path("points"))

        @ctx.commands.command("points", aliases={"积分"}, permission="points.use", plugin_name=ctx.name)
        async def points(event: MessageEvent, args: Message, command_ctx) -> None:
            data = await store.load()
            users = data.setdefault("users", {})
            user = str(event.user_id)
            await event.reply(f"当前积分：{users.get(user, 0)}")

        @ctx.commands.command("award", permission="points.award", plugin_name=ctx.name)
        async def award(event: MessageEvent, args: Message, command_ctx) -> None:
            parts = args.extract_plain_text().strip().split()
            if len(parts) != 2 or not parts[1].isdigit():
                await event.reply("用法：/award <QQ号> <积分>")
                return
            data = await store.load()
            users = data.setdefault("users", {})
            users[parts[0]] = users.get(parts[0], 0) + int(parts[1])
            await store.save()
            await event.reply(f"已给 {parts[0]} 发放 {parts[1]} 积分")


def create_plugin() -> Plugin:
    return PointsPlugin()
