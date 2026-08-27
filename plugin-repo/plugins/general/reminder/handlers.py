"""reminder 插件处理器：/remind 延迟提醒。"""

from __future__ import annotations

import functools
from datetime import timedelta
from uuid import uuid4

from app.core.messages import Message, MessageEvent
from app.core.plugin import PluginContext

_ctx: PluginContext | None = None


def setup(ctx: PluginContext) -> None:
    global _ctx
    _ctx = ctx


async def remind_command(
    event: MessageEvent, args: Message, command_ctx
) -> None:
    parts = args.extract_plain_text().strip().split(maxsplit=1)
    if len(parts) != 2 or not parts[0].isdigit():
        await event.reply("用法：/remind <秒数> <提醒内容>")
        return
    seconds = int(parts[0])
    text = parts[1]
    task_id = uuid4().hex

    async def send() -> None:
        await _ctx.send_group(getattr(event, "group_id", ""), text)

    _ctx.scheduler.add_date_job(
        functools.partial(send),
        job_id=task_id,
        run_date=_ctx.now() + timedelta(seconds=seconds),
    )
    await event.reply(f"已设置 {seconds} 秒后提醒")
