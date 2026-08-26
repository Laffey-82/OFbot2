from __future__ import annotations

from app.core.messages import Message, MessageEvent
from app.core.plugin import Plugin, PluginContext
from app.services.preset_utils import JsonStore, preset_data_path


class ExportPlugin(Plugin):
    def setup(self, ctx: PluginContext) -> None:
        store = JsonStore(preset_data_path("export"))

        @ctx.commands.command("export", aliases={"导出"}, permission="export.run", plugin_name=ctx.name)
        async def export(event: MessageEvent, args: Message, command_ctx) -> None:
            fmt = args.extract_plain_text().strip().lower() or "json"
            exporter = ctx.services.get("export")
            if exporter is None:
                await event.reply("导出服务不可用")
                return
            rows = list((await store.load()).values())
            if fmt == "csv":
                path = exporter.export_csv(rows, "export")
            else:
                path = exporter.export_json(rows, "export")
            await event.reply(f"已导出：{path}")


def create_plugin() -> Plugin:
    return ExportPlugin()
