from __future__ import annotations

from app.core.messages import Message, MessageEvent
from app.core.plugin import Plugin, PluginContext


class BackupPresetPlugin(Plugin):
    def setup(self, ctx: PluginContext) -> None:
        @ctx.commands.command("backup", aliases={"备份"}, permission="backup.run", plugin_name=ctx.name)
        async def backup(event: MessageEvent, args: Message, command_ctx) -> None:
            service = ctx.services.get("backup")
            if service is None:
                await event.reply("备份服务不可用")
                return
            from pathlib import Path

            root = Path(__file__).resolve().parents[2]
            target = service.create_backup(root / "config.yaml", root / "data" / "ofbot2.db")
            await event.reply(f"备份完成：{target}")


def create_plugin() -> Plugin:
    return BackupPresetPlugin()
