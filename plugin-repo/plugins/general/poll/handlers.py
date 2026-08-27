"""poll 插件：基于通用记录（records）的投票，选项/票数存 JSON 字符串字段。"""

from __future__ import annotations

import json

from app.core.messages import Message, MessageEvent
from app.core.plugin import PluginContext
from app.services.records import FieldSchema, RecordTypeSchema

_ctx: PluginContext | None = None


def setup(ctx: PluginContext) -> None:
    global _ctx
    _ctx = ctx
    ctx.records.schemas.register(
        RecordTypeSchema(
            "poll",
            [
                FieldSchema("topic", "string", required=True),
                FieldSchema("options", "string", required=True),
                FieldSchema("votes", "string", required=True),
                FieldSchema("creator", "string", required=False),
            ],
            description="投票记录",
        )
    )


async def poll_command(
    event: MessageEvent, args: Message, command_ctx
) -> None:
    user_id = str(getattr(event, "user_id", "") or "")
    sub = getattr(command_ctx, "subcommand", "")
    params = getattr(command_ctx, "params", None) or {}
    records = await _ctx.records.list(record_type="poll", limit=1000)

    if sub == "start":
        topic = str(params.get("topic", "")).strip()
        options = [
            item.strip()
            for item in str(params.get("options", "")).replace("，", ",").split(",")
            if item.strip()
        ]
        if len(options) < 2:
            await event.reply("至少提供两个选项，用逗号分隔")
            return
        record = await _ctx.records.create(
            "poll",
            {
                "topic": topic,
                "options": json.dumps(options, ensure_ascii=False),
                "votes": json.dumps({}, ensure_ascii=False),
                "creator": user_id,
            },
        )
        index = next(
            (i for i, item in enumerate(records + [record], start=1) if item.id == record.id),
            1,
        )
        lines = [f"#{index} {topic}"]
        lines.extend(f"{i}. {name}" for i, name in enumerate(options, start=1))
        await event.reply("\n".join(lines))
        return

    polls = [
        item
        for item in await _ctx.records.list(record_type="poll", limit=1000)
    ]
    index = int(params.get("id", 0))
    if index < 1 or index > len(polls):
        await event.reply(f"序号无效，当前共 {len(polls)} 个投票")
        return
    target = polls[index - 1]
    options = json.loads(target.data.get("options", "[]") or "[]")
    votes = json.loads(target.data.get("votes", "{}") or "{}")

    if sub == "vote":
        option = int(params.get("option", 0))
        if option < 1 or option > len(options):
            await event.reply(f"选项序号无效（1-{len(options)}）")
            return
        votes[user_id] = option
        await _ctx.records.update(
            target.id,
            {"votes": json.dumps(votes, ensure_ascii=False)},
        )
        await event.reply(f"已投票：{options[option - 1]}")
        return
    if sub == "result":
        counts = [0] * len(options)
        for option in votes.values():
            if 1 <= int(option) <= len(options):
                counts[int(option) - 1] += 1
        lines = [f"#{index} {target.data.get('topic', '')}"]
        lines.extend(
            f"{i}. {name}：{count} 票"
            for i, (name, count) in enumerate(zip(options, counts), start=1)
        )
        await event.reply("\n".join(lines))
        return
    await event.reply("用法：/poll start|vote|result")
