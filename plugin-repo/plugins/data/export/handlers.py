"""export 插件处理器：/export 导出 JSON 数据。"""

from __future__ import annotations

from app.core.messages import Message, MessageEvent
from app.core.paths import runtime_root
from app.core.plugin import PluginContext
from app.services.preset_utils import JsonStore

_ctx: PluginContext | None = None


def setup(ctx: PluginContext) -> None:
    global _ctx
    _ctx = ctx


async def export_command(
    event: MessageEvent, args: Message, command_ctx
) -> None:
    fmt = args.extract_plain_text().strip().lower() or "json"
    exporter = _ctx.services.get("export")
    if exporter is None:
        await event.reply("导出服务不可用")
        return
    store = JsonStore(runtime_root() / "data" / "presets" / "export.json")
    data = await store.load()
    rows: list = []
    for value in data.values():
        if isinstance(value, list):
            rows.extend(value)
        else:
            rows.append(value)
    try:
        if fmt == "csv":
            path = exporter.export_csv(rows, "export")
        else:
            path = exporter.export_json(rows, "export")
    except Exception as exc:
        await event.reply(f"导出失败：{exc}")
        return
    await event.reply(f"已导出：{path}")
