from __future__ import annotations

from datetime import timedelta

from app.core.messages import Message, MessageEvent
from app.core.plugin import Plugin, PluginContext
from app.services.preset_utils import JsonStore, preset_data_path


class SigninPlugin(Plugin):
    def setup(self, ctx: PluginContext) -> None:
        store = JsonStore(preset_data_path("signin"))

        @ctx.commands.command("signin", aliases={"签到"}, permission="signin.do", plugin_name=ctx.name)
        async def signin(event: MessageEvent, args: Message, command_ctx) -> None:
            user = str(event.user_id)
            today = ctx.now().date().isoformat()
            data = await store.load()
            records = data.setdefault("users", {})
            record = records.get(user, {"last": "", "streak": 0, "total": 0})
            if record["last"] == today:
                await event.reply("今天已经签到过了")
                return
            if record["last"] == (ctx.now().date() - timedelta(days=1)).isoformat():
                record["streak"] += 1
            else:
                record["streak"] = 1
            record["last"] = today
            record["total"] += 1
            records[user] = record
            await store.save()
            await event.reply(f"签到成功！连续 {record['streak']} 天，累计 {record['total']} 次")


def create_plugin() -> Plugin:
    return SigninPlugin()
