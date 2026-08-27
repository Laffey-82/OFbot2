"""audit_viewer 插件处理器：/audit 最近审计。"""

from __future__ import annotations

from app.core.messages import Message, MessageEvent
from app.core.plugin import PluginContext
from app.core.security import audit_logger

_ctx: PluginContext | None = None


def setup(ctx: PluginContext) -> None:
    global _ctx
    _ctx = ctx


async def audit_command(
    event: MessageEvent, args: Message, command_ctx
) -> None:
    logs = audit_logger.recent(10)
    if not logs:
        await event.reply("暂无审计日志")
        return
    await event.reply(
        "\n".join(f"{log['action']} {log['actor']}" for log in logs)
    )
