"""lottery 插件处理器：/lottery 随机抽取。"""

from __future__ import annotations

import random

from app.core.messages import Message, MessageEvent
from app.core.plugin import PluginContext

_ctx: PluginContext | None = None


def setup(ctx: PluginContext) -> None:
    global _ctx
    _ctx = ctx


async def lottery_command(
    event: MessageEvent, args: Message, command_ctx
) -> None:
    items = [item for item in args.extract_plain_text().split() if item]
    if not items:
        await event.reply("用法：/lottery 选项1 选项2 ...")
        return
    await event.reply(f"🎉 抽中：{random.choice(items)}")
