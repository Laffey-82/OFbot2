from __future__ import annotations

import random

from app.core.messages import Message, MessageEvent
from app.core.plugin import Plugin, PluginContext


class LotteryPlugin(Plugin):
    def setup(self, ctx: PluginContext) -> None:
        @ctx.commands.command("lottery", permission="lottery.draw", plugin_name=ctx.name)
        async def lottery(event: MessageEvent, args: Message, command_ctx) -> None:
            items = [item for item in args.extract_plain_text().split() if item]
            if not items:
                await event.reply("用法：/lottery 选项1 选项2 ...")
                return
            await event.reply(f"🎉 抽中：{random.choice(items)}")


def create_plugin() -> Plugin:
    return LotteryPlugin()
