from __future__ import annotations

from app.core.messages import Message, MessageEvent
from app.core.plugin import Plugin, PluginContext
from app.core.security import audit_logger


class AuditViewerPlugin(Plugin):
    def setup(self, ctx: PluginContext) -> None:
        @ctx.commands.command("audit", aliases={"审计"}, permission="audit_viewer.view", plugin_name=ctx.name)
        async def audit(event: MessageEvent, args: Message, command_ctx) -> None:
            logs = audit_logger.recent(10)
            if not logs:
                await event.reply("暂无审计日志")
                return
            await event.reply("\n".join(f"{log['action']} {log['actor']}" for log in logs))


def create_plugin() -> Plugin:
    return AuditViewerPlugin()
