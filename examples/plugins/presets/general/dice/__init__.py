from __future__ import annotations

import random

from app.core.messages import Message, MessageEvent
from app.core.plugin import Plugin, PluginContext


class DicePlugin(Plugin):
    def setup(self, ctx: PluginContext) -> None:
        default_max = int(ctx.config.get("max", 100))

        @ctx.commands.command("dice", permission="dice.roll", plugin_name=ctx.name)
        async def dice(event: MessageEvent, args: Message, command_ctx) -> None:
            parts = args.extract_plain_text().strip().split()
            maximum = default_max
            if parts and parts[0].isdigit():
                maximum = max(1, min(int(parts[0]), 1000000))
            await event.reply(f"🎲 {random.randint(1, maximum)}")


def create_plugin() -> Plugin:
    return DicePlugin()
