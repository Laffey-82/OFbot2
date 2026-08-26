from __future__ import annotations

from app.core.messages import Message, MessageEvent
from app.core.plugin import Plugin, PluginContext
from app.services.preset_utils import JsonStore, preset_data_path


class DutyPlugin(Plugin):
    def setup(self, ctx: PluginContext) -> None:
        store = JsonStore(preset_data_path("duty"))

        @ctx.commands.command("duty", aliases={"值班"}, permission="duty.use", plugin_name=ctx.name)
        async def duty(event: MessageEvent, args: Message, command_ctx) -> None:
            parts = args.extract_plain_text().strip().split(maxsplit=1)
            action = parts[0].lower() if parts else "list"
            data = await store.load()
            rows = data.setdefault("rows", [])
            if action == "add" and len(parts) == 2:
                date, name = parts[1].split(maxsplit=1)
                rows.append({"date": date, "name": name})
                await store.save()
                await event.reply("已添加值班")
                return
            if action == "list":
                await event.reply("\n".join(f"{r['date']} {r['name']}" for r in rows) or "暂无值班安排")
                return
            await event.reply("用法：/duty add <日期> <姓名> | list")


def create_plugin() -> Plugin:
    return DutyPlugin()
