"""stats 插件处理器：群消息统计。"""

from __future__ import annotations

from app.core.events import GroupMessageReceived
from app.core.messages import Message, MessageEvent
from app.core.paths import runtime_root
from app.core.plugin import PluginContext
from app.services.preset_utils import JsonStore

_ctx: PluginContext | None = None
_store: JsonStore | None = None


def setup(ctx: PluginContext) -> None:
    global _ctx, _store
    _ctx = ctx
    _store = JsonStore(runtime_root() / "data" / "presets" / "stats.json")


async def on_group_message(event: GroupMessageReceived) -> None:
    data = await _store.load()
    group = data.setdefault(event.group_id, {"messages": 0, "users": {}})
    group["messages"] += 1
    group["users"][event.user_id] = group["users"].get(event.user_id, 0) + 1
    await _store.save()


async def stats_command(
    event: MessageEvent, args: Message, command_ctx
) -> None:
    data = await _store.load()
    group_id = getattr(event, "group_id", "private")
    group = data.get(group_id)
    if group is None:
        await event.reply("暂无统计数据")
        return
    await event.reply(
        f"消息数：{group['messages']}\n活跃用户：{len(group['users'])}"
    )
