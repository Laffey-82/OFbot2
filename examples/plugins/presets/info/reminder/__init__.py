from __future__ import annotations

import functools
from datetime import timedelta
from uuid import uuid4

from app.core.messages import Message, MessageEvent
from app.core.plugin import Plugin, PluginContext


class ReminderPlugin(Plugin):
    def setup(self, ctx: PluginContext) -> None:
        @ctx.commands.command("remind", aliases={"提醒"}, permission="reminder.use", plugin_name=ctx.name)
        async def remind(event: MessageEvent, args: Message, command_ctx) -> None:
            parts = args.extract_plain_text().strip().split(maxsplit=1)
            if len(parts) != 2 or not parts[0].isdigit():
                await event.reply("用法：/remind <秒数> <提醒内容>")
                return
            seconds = int(parts[0])
            text = parts[1]
            task_id = uuid4().hex

            async def send() -> None:
                await ctx.send_group(getattr(event, "group_id", ""), text)

            ctx.scheduler.add_date_job(
                functools.partial(send),
                job_id=task_id,
                run_date=ctx.now() + timedelta(seconds=seconds),
            )
            await event.reply(f"已设置 {seconds} 秒后提醒")


def create_plugin() -> Plugin:
    return ReminderPlugin()
