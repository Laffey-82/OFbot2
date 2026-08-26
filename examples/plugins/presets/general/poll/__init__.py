from __future__ import annotations

from uuid import uuid4

from app.core.messages import Message, MessageEvent
from app.core.plugin import Plugin, PluginContext
from app.services.preset_utils import JsonStore, preset_data_path


class PollPlugin(Plugin):
    def setup(self, ctx: PluginContext) -> None:
        store = JsonStore(preset_data_path("poll"))

        @ctx.commands.command("poll", permission="poll.use", plugin_name=ctx.name)
        async def poll(event: MessageEvent, args: Message, command_ctx) -> None:
            text = args.extract_plain_text().strip()
            if not text:
                await event.reply("用法：/poll 问题|选项1|选项2")
                return
            parts = [part.strip() for part in text.split("|") if part.strip()]
            if len(parts) < 3:
                await event.reply("至少需要 1 个问题和 2 个选项")
                return
            poll_id = uuid4().hex[:8]
            data = await store.load()
            data.setdefault("polls", {})[poll_id] = {
                "question": parts[0],
                "options": parts[1:],
                "votes": {option: [] for option in parts[1:]},
            }
            await store.save()
            await event.reply(
                f"投票已创建：{poll_id}\n{parts[0]}\n" + "\n".join(f"{i+1}. {o}" for i, o in enumerate(parts[1:]))
            )

        @ctx.commands.command("vote", permission="poll.use", plugin_name=ctx.name)
        async def vote(event: MessageEvent, args: Message, command_ctx) -> None:
            parts = args.extract_plain_text().strip().split(maxsplit=1)
            if len(parts) != 2:
                await event.reply("用法：/vote <投票ID> <选项序号>")
                return
            poll_id, option_text = parts
            data = await store.load()
            poll_data = data.get("polls", {}).get(poll_id)
            if poll_data is None:
                await event.reply("投票不存在")
                return
            if not option_text.isdigit() or int(option_text) < 1 or int(option_text) > len(poll_data["options"]):
                await event.reply("选项序号无效")
                return
            option = poll_data["options"][int(option_text) - 1]
            user = str(event.user_id)
            for voters in poll_data["votes"].values():
                voters[:] = [v for v in voters if v != user]
            poll_data["votes"][option].append(user)
            await store.save()
            await event.reply(f"已投票：{option}")


def create_plugin() -> Plugin:
    return PollPlugin()
