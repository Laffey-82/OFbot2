from __future__ import annotations

from uuid import uuid4

from app.core.messages import Message, MessageEvent
from app.core.plugin import Plugin, PluginContext
from app.services.preset_utils import JsonStore, preset_data_path


class TodoPlugin(Plugin):
    def setup(self, ctx: PluginContext) -> None:
        store = JsonStore(preset_data_path("todo"))

        @ctx.commands.command("todo", aliases={"待办"}, permission="todo.use", plugin_name=ctx.name)
        async def todo(event: MessageEvent, args: Message, command_ctx) -> None:
            parts = args.extract_plain_text().strip().split(maxsplit=1)
            action = parts[0].lower() if parts else "list"
            data = await store.load()
            user = str(event.user_id)
            items = data.setdefault(user, [])
            if action == "add" and len(parts) == 2:
                items.append({"id": uuid4().hex[:8], "text": parts[1], "done": False})
                await store.save()
                await event.reply("已添加待办")
                return
            if action == "list":
                await event.reply("\n".join(f"{'✅' if i['done'] else '⬜'} {i['id']} {i['text']}" for i in items) or "暂无待办")
                return
            if action == "done" and len(parts) == 2:
                for item in items:
                    if item["id"] == parts[1]:
                        item["done"] = True
                        await store.save()
                        await event.reply("已完成")
                        return
                await event.reply("待办不存在")
                return
            await event.reply("用法：/todo add <内容> | list | done <id>")


def create_plugin() -> Plugin:
    return TodoPlugin()
