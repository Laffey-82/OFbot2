from __future__ import annotations

from app.core.messages import Message, MessageEvent
from app.core.plugin import Plugin, PluginContext


class HealthCheckPlugin(Plugin):
    def setup(self, ctx: PluginContext) -> None:
        @ctx.commands.command("health", aliases={"健康"}, permission="health_check.view", plugin_name=ctx.name)
        async def health(event: MessageEvent, args: Message, command_ctx) -> None:
            adapters = getattr(ctx.bot, "status", {})
            await event.reply(f"健康检查通过\n适配器：{adapters}")


def create_plugin() -> Plugin:
    return HealthCheckPlugin()
