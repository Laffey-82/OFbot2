from __future__ import annotations

from app.core.messages import Message, MessageEvent
from app.core.plugin import Plugin, PluginContext
from app.services.preset_utils import format_money


class CommissionPlugin(Plugin):
    def setup(self, ctx: PluginContext) -> None:
        @ctx.commands.command("commission", aliases={"分账"}, permission="commission.use", plugin_name=ctx.name)
        async def commission(event: MessageEvent, args: Message, command_ctx) -> None:
            text = args.extract_plain_text().strip()
            try:
                price = float(text)
            except ValueError:
                await event.reply("用法：/commission <金额>")
                return
            parts = [
                ("打手", 0.68),
                ("接单人", 0.18),
                ("OF", 0.09),
                ("应急公款", 0.05),
            ]
            await event.reply(
                "\n".join(f"{name}：{format_money(price * ratio)}" for name, ratio in parts)
            )


def create_plugin() -> Plugin:
    return CommissionPlugin()
