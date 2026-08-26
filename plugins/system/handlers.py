"""system 插件模块级命令处理器（由 plugin.json features 声明引用）。"""

from __future__ import annotations

import functools
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, select

from app.core.messages import Message, MessageEvent
from app.core.parsing import build_usage
from app.core.plugin import PluginContext
from app.db.models import Task, TaskRun

_ctx: PluginContext | None = None


def setup(ctx: PluginContext) -> None:
    global _ctx
    _ctx = ctx
    if _ctx.services.get("whitelist") is None:
        from app.core.whitelist import GroupWhitelistService

        _ctx.services["whitelist"] = GroupWhitelistService(
            _ctx.config.get("groups", [])
        )


def _whitelist():
    return _ctx.services.get("whitelist")


def _prefix() -> str:
    """当前生效的命令前缀（首个），供帮助与用法文案使用。"""
    if _ctx is not None and _ctx.commands is not None:
        prefixes = getattr(_ctx.commands, "command_start", None)
        if prefixes:
            return str(prefixes[0])
    return "/"


def _render_usage(usage: str) -> str:
    """把 usage 中的默认 "/" 前缀替换为实际生效前缀。"""
    if not usage:
        return ""
    prefix = _prefix()
    if usage.startswith("/"):
        return prefix + usage[1:]
    return usage


def _render_examples(examples: list) -> list[str]:
    prefix = _prefix()
    rendered = []
    for example in examples:
        text = str(example)
        if text.startswith("/"):
            text = prefix + text[1:]
        rendered.append(text)
    return rendered


def _visible_commands(commands: list, command_ctx) -> list:
    """按当前监听环境过滤：该环境未开启的功能命令不展示。"""
    if _ctx is None or _ctx.scope_policy is None or command_ctx is None:
        return commands
    scope = getattr(command_ctx, "scope", "")
    if not scope:
        return commands
    visible = []
    for command in commands:
        if not command.feature_id:
            visible.append(command)
            continue
        plugin, _, feature_id = command.feature_id.partition(".")
        if _ctx.scope_policy.feature_enabled(plugin, feature_id, scope):
            visible.append(command)
    return visible


async def help_command(
    event: MessageEvent, args: Message, command_ctx
) -> None:
    query = args.extract_plain_text().strip().lower()
    commands = _visible_commands(_ctx.commands.get_commands(), command_ctx)
    if query:
        target = next(
            (
                command
                for command in commands
                if command.name == query
                or query in {alias.lower() for alias in command.aliases}
            ),
            None,
        )
        if target is None:
            await event.reply(
                f"未找到命令 {query}，发送 {_prefix()}help 查看全部命令"
            )
            return
        lines = [f"{_prefix()}{target.name}：{target.description or '（无说明）'}"]
        if target.aliases:
            lines.append("别名：" + " / ".join(sorted(target.aliases)))
        if target.usage:
            lines.append(f"用法：{_render_usage(target.usage)}")
        elif target.params or target.subcommands:
            lines.append(
                f"用法：{_prefix()}"
                f"{build_usage(target.name, target.params, target.subcommands)}"
            )
        if target.subcommands:
            sub_lines = []
            for sub in target.subcommands:
                sub_lines.append(
                    f"{sub.name}（{sub.description or '无说明'}）"
                )
            lines.append("子命令：" + " ｜ ".join(sub_lines))
        if target.examples:
            lines.append("示例：" + " ｜ ".join(_render_examples(target.examples)))
        if target.permission:
            lines.append(f"权限：{target.permission}")
        if target.cooldown:
            lines.append(f"冷却：{target.cooldown}s")
        if target.rate_limit:
            lines.append(f"限流：{target.rate_limit}")
        await event.reply("\n".join(lines))
        return

    by_plugin: dict[str, list] = {}
    for command in commands:
        by_plugin.setdefault(command.plugin_name or "未归属", []).append(command)
    total = len(commands)
    lines = [
        f"OFbot 2 命令帮助（共 {total} 条），发送 {_prefix()}help <命令> 查看详情"
    ]
    for plugin in sorted(by_plugin):
        items = by_plugin[plugin]
        for command in items[:8]:
            suffix = f"：{command.description}" if command.description else ""
            lines.append(f"{_prefix()}{command.name}{suffix}")
        if len(items) > 8:
            lines.append(f"…{plugin} 共 {len(items)} 条")
    text = "\n".join(lines)
    if len(text) > 1800:
        for start in range(0, len(text), 1800):
            await event.reply(text[start : start + 1800])
        return
    await event.reply(text)


async def about_command(
    event: MessageEvent, args: Message, command_ctx
) -> None:
    from app import __version__

    capabilities = sorted(cap.name for cap in _ctx.capabilities.list())
    preview = "、".join(capabilities[:12])
    if len(capabilities) > 12:
        preview += "…"
    await event.reply(
        "\n".join(
            [
                f"OFbot 2 v{__version__}",
                "插件化 QQ 机器人框架：Red / OneBot（v11/v12）、Satori、Mirai、官方机器人",
                f"核心能力：{preview or '—'}",
                "Web 后台文档：/docs/view/readme",
            ]
        )
    )


async def echo_command(
    event: MessageEvent, args: Message, command_ctx
) -> None:
    text = args.extract_plain_text().strip()
    sender = getattr(event, "user_id", "?")
    group = getattr(event, "group_id", "?")
    when = datetime.now(UTC).strftime("%H:%M:%S")
    await event.reply(
        f"【回声 {when}】{text or '（空）'}\n来自：{sender}（群 {group}）"
    )


async def whitelist_command(
    event: MessageEvent, args: Message, command_ctx
) -> None:
    service = _whitelist()
    if service is None:
        await event.reply("白名单服务不可用")
        return
    parts = args.extract_plain_text().strip().split()
    if not parts:
        await event.reply(f"用法：{_prefix()}whitelist add|del|list [群号]")
        return
    action = parts[0].lower()
    if action == "list":
        await event.reply(
            "白名单群："
            + (", ".join(service.list()) if service.list() else "空")
        )
        return
    if action == "add" and len(parts) >= 2:
        added = service.add(parts[1])
        await event.reply(
            f"已添加群 {parts[1]}" if added else f"群 {parts[1]} 已在白名单"
        )
        return
    if action == "del" and len(parts) >= 2:
        removed = service.remove(parts[1])
        await event.reply(
            f"已删除群 {parts[1]}" if removed else f"群 {parts[1]} 不在白名单"
        )
        return
    await event.reply(f"用法：{_prefix()}whitelist add|del|list [群号]")


async def plugins_command(
    event: MessageEvent, args: Message, command_ctx
) -> None:
    loaded = getattr(
        _ctx.services.get("plugin_manager"), "get_loaded_plugins", list
    )()
    await event.reply(
        "已加载插件：" + ", ".join(item["name"] for item in loaded)
    )


async def status_command(
    event: MessageEvent, args: Message, command_ctx
) -> None:
    from app import __version__

    plugins = getattr(
        _ctx.services.get("plugin_manager"), "get_loaded_plugins", list
    )()
    adapter_status = getattr(_ctx.bot, "status", {})
    async with _ctx.db() as session:
        total_tasks = (
            await session.scalar(select(func.count()).select_from(Task))
        ) or 0
        enabled_tasks = (
            await session.scalar(
                select(func.count())
                .select_from(Task)
                .where(Task.enabled.is_(True))
            )
        ) or 0
    adapter_part = (
        "、".join(
            f"{name}={state}" for name, state in adapter_status.items()
        )
        if adapter_status
        else "未连接"
    )
    await event.reply(
        "\n".join(
            [
                f"OFbot 2 v{__version__}",
                f"插件：{len(plugins)} 个已加载",
                f"任务：{enabled_tasks}/{total_tasks} 启用",
                f"适配器：{adapter_part}",
            ]
        )
    )


async def execute_task(task_id: str) -> None:
    async with _ctx.db() as session:
        task = await session.scalar(
            select(Task).where(Task.task_id == task_id)
        )
        if task is None or not task.enabled:
            return
        task.status = "running"
        task.last_run_time = datetime.now(UTC)
        await session.commit()
        try:
            group_id = task.params.get("group_id")
            message = task.params.get("message", "")
            if group_id and message:
                await _ctx.bot.send_group_message(str(group_id), message)
            task.status = "succeeded"
        except Exception as exc:
            task.status = "failed"
            task.params = {**task.params, "last_error": str(exc)}
        session.add(
            TaskRun(
                task_id=task.task_id,
                status=task.status,
                message=task.params.get("last_error", ""),
            )
        )
        await session.commit()


async def task_command(
    event: MessageEvent, args: Message, command_ctx
) -> None:
    parts = args.extract_plain_text().strip().split()
    if not parts or parts[0] == "list":
        async with _ctx.db() as session:
            tasks = (
                await session.scalars(
                    select(Task).order_by(Task.created_at.desc()).limit(50)
                )
            ).all()
        if not tasks:
            await event.reply("暂无定时任务")
            return
        await event.reply(
            "\n".join(
                f"{'✅' if task.enabled else '❌'} {task.task_id[:8]} {task.name} ({task.type})"
                for task in tasks
            )
        )
        return

    action = parts[0].lower()
    if action == "add" and len(parts) >= 6:
        task_type = parts[1]
        name = parts[2]
        group_id = parts[3]
        message = " ".join(parts[5:])
        task_id = uuid4().hex
        if task_type == "interval":
            seconds = parts[4]
            if not seconds.isdigit():
                await event.reply("间隔时间必须为数字")
                return
            async with _ctx.db() as session:
                session.add(
                    Task(
                        task_id=task_id,
                        name=name,
                        type="interval",
                        interval_seconds=int(seconds),
                        params={"group_id": group_id, "message": message},
                        enabled=True,
                    )
                )
                await session.commit()
            _ctx.scheduler.add_interval_job(
                functools.partial(execute_task, task_id),
                job_id=task_id,
                seconds=int(seconds),
            )
            await event.reply(f"任务已创建：{task_id[:8]}")
            return
        if task_type == "cron":
            cron_expression = parts[4]
            async with _ctx.db() as session:
                session.add(
                    Task(
                        task_id=task_id,
                        name=name,
                        type="cron",
                        cron_expression=cron_expression,
                        params={"group_id": group_id, "message": message},
                        enabled=True,
                    )
                )
                await session.commit()
            try:
                _ctx.scheduler.add_cron_job(
                    functools.partial(execute_task, task_id),
                    job_id=task_id,
                    cron_expression=cron_expression,
                )
            except Exception as exc:
                async with _ctx.db() as session:
                    task = await session.scalar(
                        select(Task).where(Task.task_id == task_id)
                    )
                    if task:
                        await session.delete(task)
                        await session.commit()
                await event.reply(f"任务创建失败：{exc}")
                return
            await event.reply(f"任务已创建：{task_id[:8]}")
            return
        await event.reply("任务类型仅支持 interval 或 cron")
        return

    if action in {"remove", "enable", "disable"} and len(parts) >= 2:
        task_id = parts[1]
        async with _ctx.db() as session:
            task = await session.scalar(
                select(Task).where(Task.task_id == task_id)
            )
            if task is None:
                task = await session.scalar(
                    select(Task)
                    .where(Task.task_id.startswith(task_id))
                    .limit(1)
                )
            if task is None:
                await event.reply("任务不存在")
                return
            task_id = task.task_id
            if action == "remove":
                await session.delete(task)
                _ctx.scheduler.remove_job(task_id)
                await session.commit()
                await event.reply("任务已删除")
                return
            task.enabled = action == "enable"
            await session.commit()
        if action == "enable":
            if task.type == "cron" and task.cron_expression:
                _ctx.scheduler.add_cron_job(
                    functools.partial(execute_task, task_id),
                    job_id=task_id,
                    cron_expression=task.cron_expression,
                )
            elif task.type == "interval" and task.interval_seconds:
                _ctx.scheduler.add_interval_job(
                    functools.partial(execute_task, task_id),
                    job_id=task_id,
                    seconds=task.interval_seconds,
                )
            await event.reply("任务已启用")
        else:
            _ctx.scheduler.remove_job(task_id)
            await event.reply("任务已停用")
        return

    await event.reply(
        f"用法：{_prefix()}task list ｜ {_prefix()}task run <id> ｜ "
        f"{_prefix()}task enable|disable|remove <id> ｜ "
        f"{_prefix()}task add interval|cron <名称> <群号> <参数> <消息>"
    )
