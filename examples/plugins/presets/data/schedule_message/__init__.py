from __future__ import annotations

import functools
from datetime import timedelta
from uuid import uuid4

from app.core.messages import Message, MessageEvent
from app.core.plugin import Plugin, PluginContext


class ScheduleMessagePlugin(Plugin):
    def setup(self, ctx: PluginContext) -> None:
        @ctx.commands.command("schedule", permission="schedule_message.use", plugin_name=ctx.name)
        async def schedule(event: MessageEvent, args: Message, command_ctx) -> None:
            parts = args.extract_plain_text().strip().split(maxsplit=2)
            if len(parts) != 3 or not parts[0].isdigit():
                await event.reply("用法：/schedule <秒数> <群号> <消息>")
                return
            seconds, group_id, message = int(parts[0]), parts[1], parts[2]

            async def send() -> None:
                await ctx.send_group(group_id, message)

            ctx.scheduler.add_date_job(
                functools.partial(send),
                job_id=uuid4().hex,
                run_date=ctx.now() + timedelta(seconds=seconds),
            )
            await event.reply("定时消息已设置")


def create_plugin() -> Plugin:
    return ScheduleMessagePlugin()
