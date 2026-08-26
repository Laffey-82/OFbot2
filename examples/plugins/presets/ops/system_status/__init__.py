from __future__ import annotations

from app.core.messages import Message, MessageEvent
from app.core.plugin import Plugin, PluginContext


class SystemStatusPlugin(Plugin):
    def setup(self, ctx: PluginContext) -> None:
        @ctx.commands.command("system", aliases={"系统状态"}, permission="system_status.view", plugin_name=ctx.name)
        async def system(event: MessageEvent, args: Message, command_ctx) -> None:
            manager = ctx.services.get("plugin_manager")
            count = len(manager.get_loaded_plugins()) if manager else 0
            await event.reply(f"OFbot 2 运行正常\n已加载插件：{count}")


def create_plugin() -> Plugin:
    return SystemStatusPlugin()
