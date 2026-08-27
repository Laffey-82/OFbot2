"""duty 插件处理器：/duty 值班排班。"""

from __future__ import annotations

from app.core.messages import Message, MessageEvent
from app.core.paths import runtime_root
from app.core.plugin import PluginContext
from app.services.preset_utils import JsonStore

_ctx: PluginContext | None = None
_store: JsonStore | None = None


def setup(ctx: PluginContext) -> None:
    global _ctx, _store
    _ctx = ctx
    path = runtime_root() / "data" / "presets" / "duty.json"
    _store = JsonStore(path)


async def duty_command(
    event: MessageEvent, args: Message, command_ctx
) -> None:
    parts = args.extract_plain_text().strip().split(maxsplit=1)
    action = parts[0].lower() if parts else "list"
    data = await _store.load()
    rows = data.setdefault("rows", [])
    if action == "add" and len(parts) == 2:
        date, name = parts[1].split(maxsplit=1)
        rows.append({"date": date, "name": name})
        await _store.save()
        await event.reply("已添加值班")
        return
    if action == "list":
        await event.reply(
            "\n".join(f"{r['date']} {r['name']}" for r in rows)
            or "暂无值班安排"
        )
        return
    await event.reply("用法：/duty add <日期> <姓名> | list")
