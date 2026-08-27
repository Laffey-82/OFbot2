"""backup 插件处理器：/backup 手动备份。"""

from __future__ import annotations

from app.core.messages import Message, MessageEvent
from app.core.paths import runtime_root
from app.core.plugin import PluginContext

_ctx: PluginContext | None = None


def setup(ctx: PluginContext) -> None:
    global _ctx
    _ctx = ctx


async def backup_command(
    event: MessageEvent, args: Message, command_ctx
) -> None:
    service = _ctx.services.get("backup")
    if service is None:
        await event.reply("备份服务不可用")
        return
    root = runtime_root()
    target = service.create_backup(
        root / "config.yaml", root / "data" / "ofbot2.db"
    )
    await event.reply(f"备份完成：{target}")
