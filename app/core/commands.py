from __future__ import annotations

import difflib
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from app.core.bus import get_bus
from app.core.events import (
    CommandFailed,
    CommandInvoked,
    CommandParsed,
    CommandRejected,
)
from app.core.logger import get_logger, get_trace_id
from app.core.messages import Message, MessageEvent
from app.core.parsing import (
    ParamSpec,
    SubcommandSpec,
    bind_params,
    build_usage,
    resolve_subcommand,
)
from app.core.permissions import permission_manager
from app.core.rules import RuleRegistry, RuleSpec
from app.core.scopes import resolve_scope
from app.core.security import (
    SecurityPolicy,
    audit_logger,
    parse_rate_limit,
)

logger = get_logger(__name__)

CommandHandler = Callable[[MessageEvent, Message, "CommandContext"], Awaitable[Any]]


def _strip_at_self(text: str, self_id: str = "") -> str:
    """剥离 @bot 前缀与 at 占位（官方机器人仅收 @ 消息时使用）。"""
    text = text.strip()
    if self_id:
        text = text.replace(f"[@{self_id}]", "").strip()
    if text.startswith("@"):
        head, _, rest = text.partition(" ")
        head = head.lstrip("@").strip()
        if not head or (self_id and head == self_id):
            return rest.strip()
    return text


@dataclass(slots=True)
class CommandContext:
    command_name: str
    args: str
    plugin_name: str = ""
    permission: str = ""
    feature_id: str = ""
    scope: str = ""
    connection_id: str = ""
    subcommand: str = ""
    params: dict[str, Any] | None = None
    session: Any = None
    trace_id: str = ""
    raw_event: Any = None


@dataclass(slots=True)
class Command:
    name: str
    handler: CommandHandler
    aliases: set[str] = field(default_factory=set)
    priority: int = 10
    block: bool = True
    permission: str = "bot.command"
    cooldown: float = 0.0
    rate_limit: str | None = None
    plugin_name: str = ""
    description: str = ""
    feature_id: str = ""
    usage: str = ""
    examples: list[str] = field(default_factory=list)
    params: list[ParamSpec] = field(default_factory=list)
    subcommands: list[SubcommandSpec] = field(default_factory=list)
    rules: list[RuleSpec] = field(default_factory=list)
    session: bool = False


class CommandRegistry:
    def __init__(self) -> None:
        self._commands: dict[str, Command] = {}
        self._by_plugin: dict[str, set[str]] = {}
        self.command_start: list[str] = ["/", "!"]
        self.command_sep: list[str] = ["."]
        self.security: SecurityPolicy | None = None
        self.stat_callback: Callable[..., Any] | None = None
        self.scope_policy: Any = None
        self.unknown_command_hint: bool = True
        self.rules: RuleRegistry | None = None
        self.session_manager: Any = None

    def set_scope_policy(self, policy: Any) -> None:
        self.scope_policy = policy

    def set_rule_registry(self, registry: RuleRegistry) -> None:
        self.rules = registry

    def set_session_manager(self, manager: Any) -> None:
        self.session_manager = manager

    def set_command_start(self, prefixes: list[str]) -> None:
        self.command_start = prefixes

    def set_command_sep(self, separators: list[str]) -> None:
        self.command_sep = separators or ["."]

    def set_security(self, policy: SecurityPolicy) -> None:
        self.security = policy

    def set_stat_callback(self, callback: Callable[..., Any]) -> None:
        self.stat_callback = callback

    def command(
        self,
        name: str,
        *,
        aliases: Iterable[str] | None = None,
        priority: int = 10,
        block: bool = True,
        permission: str = "bot.command",
        cooldown: float = 0.0,
        rate_limit: str | None = None,
        plugin_name: str = "",
        description: str = "",
        feature_id: str = "",
        usage: str = "",
        examples: Iterable[str] | None = None,
        params: Iterable[ParamSpec] | None = None,
        subcommands: Iterable[SubcommandSpec] | None = None,
        rules: Iterable[RuleSpec] | None = None,
        session: bool = False,
    ) -> Callable[[CommandHandler], CommandHandler]:
        def decorator(func: CommandHandler) -> CommandHandler:
            self.register(
                name,
                func,
                aliases=set(aliases or []),
                priority=priority,
                block=block,
                permission=permission,
                cooldown=cooldown,
                rate_limit=rate_limit,
                plugin_name=plugin_name,
                description=description,
                feature_id=feature_id,
                usage=usage,
                examples=list(examples or []),
                params=self._coerce_params(params),
                subcommands=self._coerce_subcommands(subcommands),
                rules=self._coerce_rules(rules),
                session=session,
            )
            return func

        return decorator

    @staticmethod
    def _coerce_params(
        params: Iterable[ParamSpec | dict] | None,
    ) -> list[ParamSpec]:
        return [
            ParamSpec.model_validate(item)
            if isinstance(item, dict)
            else item
            for item in (params or [])
        ]

    @staticmethod
    def _coerce_subcommands(
        subcommands: Iterable[SubcommandSpec | dict] | None,
    ) -> list[SubcommandSpec]:
        return [
            SubcommandSpec.model_validate(item)
            if isinstance(item, dict)
            else item
            for item in (subcommands or [])
        ]

    @staticmethod
    def _coerce_rules(
        rules: Iterable[RuleSpec | dict] | None,
    ) -> list[RuleSpec]:
        return [
            RuleSpec.model_validate(item)
            if isinstance(item, dict)
            else item
            for item in (rules or [])
        ]

    def register(
        self,
        name: str,
        handler: CommandHandler,
        *,
        aliases: set[str] | None = None,
        priority: int = 10,
        block: bool = True,
        permission: str = "bot.command",
        cooldown: float = 0.0,
        rate_limit: str | None = None,
        plugin_name: str = "",
        description: str = "",
        feature_id: str = "",
        usage: str = "",
        examples: Iterable[str] | None = None,
        params: Iterable[ParamSpec] | None = None,
        subcommands: Iterable[SubcommandSpec] | None = None,
        rules: Iterable[RuleSpec] | None = None,
        session: bool = False,
    ) -> Command:
        command = Command(
            name=name,
            handler=handler,
            aliases=aliases or set(),
            priority=priority,
            block=block,
            permission=permission,
            cooldown=cooldown,
            rate_limit=rate_limit,
            plugin_name=plugin_name,
            description=description,
            feature_id=feature_id,
            usage=usage,
            examples=list(examples or []),
            params=self._coerce_params(params),
            subcommands=self._coerce_subcommands(subcommands),
            rules=self._coerce_rules(rules),
            session=session,
        )
        self._commands[name] = command
        if plugin_name:
            self._by_plugin.setdefault(plugin_name, set()).add(name)
        for alias in command.aliases:
            self._commands[alias] = command
            if plugin_name:
                self._by_plugin[plugin_name].add(alias)
        return command

    def unregister_plugin(self, plugin_name: str) -> int:
        names = self._by_plugin.pop(plugin_name, set())
        for name in names:
            command = self._commands.pop(name, None)
            if command:
                for alias in command.aliases:
                    self._commands.pop(alias, None)
        return len(names)

    def parse(self, text: str) -> tuple[str, str] | None:
        text = text.strip()
        for prefix in self.command_start:
            if text.startswith(prefix):
                content = text[len(prefix) :].lstrip()
                if not content:
                    return None
                parts = content.split(maxsplit=1)
                name = parts[0]
                args = parts[1] if len(parts) > 1 else ""
                for sep in self.command_sep:
                    if sep and sep in name:
                        head, _, tail = name.partition(sep)
                        if head:
                            combined = (tail + (" " + args if args else "")).strip()
                            return head, combined
                return name, args
        return None

    def suggest(self, name: str, limit: int = 3) -> list[str]:
        """根据命令名与别名做模糊建议（diff 相似度）。"""
        candidates: set[str] = set()
        for command in self._commands.values():
            candidates.add(command.name)
            candidates.update(command.aliases)
        matches = difflib.get_close_matches(
            name, sorted(candidates), n=limit, cutoff=0.45
        )
        return matches

    async def handle_message(self, event: MessageEvent) -> bool:
        text = event.message.extract_plain_text().strip()
        at_self = getattr(event, "at_self", False)
        if at_self:
            text = _strip_at_self(text, getattr(event, "self_id", ""))
        parsed = self.parse(text)
        if parsed is None:
            return False

        command_name, args = parsed
        command = self._commands.get(command_name)
        if command is None:
            if self.unknown_command_hint:
                prefix = (self.command_start or ["/"])[0]
                suggestions = self.suggest(command_name)
                if suggestions:
                    hint = "、".join(f"{prefix}{name}" for name in suggestions)
                    await event.reply(
                        f"未找到命令 {prefix}{command_name}，是否想用 {hint}？发送 {prefix}help 查看全部命令"
                    )
                else:
                    await event.reply(
                        f"未找到命令 {prefix}{command_name}，发送 {prefix}help 查看全部命令"
                    )
            return False

        bus = get_bus()
        bus.dispatch(
            CommandParsed(
                bot_id=getattr(event, "bot_id", ""),
                self_id=getattr(event, "self_id", ""),
                user_id=getattr(event, "user_id", ""),
                group_id=getattr(event, "group_id", ""),
                command_name=command.name,
                args=args,
            )
        )

        user_id = str(getattr(event, "user_id", ""))
        group_id = str(getattr(event, "group_id", ""))
        scope = resolve_scope(group_id)
        connection_id = str(getattr(event, "bot_id", ""))
        policy = self.security
        if policy:
            blocked = policy.check_blocked(user_id) or (
                self.scope_policy is not None
                and self.scope_policy.is_blocked(user_id, scope)
            )
            if blocked:
                reason = "用户已被拉黑"
                bus.dispatch(
                    CommandRejected(
                        bot_id=getattr(event, "bot_id", ""),
                        self_id=getattr(event, "self_id", ""),
                        user_id=user_id,
                        group_id=group_id,
                        command_name=command.name,
                        reason=reason,
                    )
                )
                audit_logger.record(
                    "command.rejected",
                    user_id,
                    target=command.name,
                    success=False,
                    detail={"reason": reason},
                )
                return command.block
            validation_error = policy.validate_text(text)
            if validation_error:
                bus.dispatch(
                    CommandRejected(
                        bot_id=getattr(event, "bot_id", ""),
                        self_id=getattr(event, "self_id", ""),
                        user_id=user_id,
                        group_id=group_id,
                        command_name=command.name,
                        reason=validation_error,
                    )
                )
                await event.reply(f"【×】{validation_error}")
                return command.block
            if (
                command.feature_id
                and self.scope_policy is not None
                and not self.scope_policy.feature_enabled(
                    command.plugin_name,
                    command.feature_id.split(".", 1)[-1],
                    scope,
                )
            ):
                reason = "feature.disabled"
                bus.dispatch(
                    CommandRejected(
                        bot_id=getattr(event, "bot_id", ""),
                        self_id=getattr(event, "self_id", ""),
                        user_id=user_id,
                        group_id=group_id,
                        command_name=command.name,
                        reason=reason,
                    )
                )
                audit_logger.record(
                    "command.rejected",
                    user_id,
                    target=command.name,
                    success=False,
                    detail={"reason": reason, "scope": scope},
                )
                if not (
                    self.scope_policy is not None
                    and self.scope_policy.silent_deny(scope)
                ):
                    if scope.startswith("group:"):
                        await event.reply(
                            "【未开启】该功能在本群未开启，如需使用请联系群管理员"
                        )
                    else:
                        await event.reply(
                            "【未开启】该功能当前未开启，如需使用请联系管理员"
                        )
                return command.block
            if command.cooldown and not policy.check_cooldown(
                f"cooldown:{user_id}:{command.name}", command.cooldown
            ):
                reason = "操作过于频繁"
                bus.dispatch(
                    CommandRejected(
                        bot_id=getattr(event, "bot_id", ""),
                        self_id=getattr(event, "self_id", ""),
                        user_id=user_id,
                        group_id=group_id,
                        command_name=command.name,
                        reason=reason,
                    )
                )
                await event.reply(f"【×】{reason}")
                return command.block
            rate_spec = (
                parse_rate_limit(command.rate_limit)
                if command.rate_limit
                else policy.rate_limit_default
            )
            if not policy.check_rate(
                f"rate:{user_id}:{command.name}", rate_spec
            ):
                reason = "触发频率限制"
                bus.dispatch(
                    CommandRejected(
                        bot_id=getattr(event, "bot_id", ""),
                        self_id=getattr(event, "self_id", ""),
                        user_id=user_id,
                        group_id=group_id,
                        command_name=command.name,
                        reason=reason,
                    )
                )
                await event.reply(f"【×】{reason}")
                return command.block

        if command.rules and self.rules is not None:
            passed, rule_reason = await self.rules.check(
                command.rules, event
            )
            if not passed:
                reason = rule_reason or "rule.mismatch"
                bus.dispatch(
                    CommandRejected(
                        bot_id=getattr(event, "bot_id", ""),
                        self_id=getattr(event, "self_id", ""),
                        user_id=user_id,
                        group_id=group_id,
                        command_name=command.name,
                        reason=reason,
                    )
                )
                audit_logger.record(
                    "command.rejected",
                    user_id,
                    target=command.name,
                    success=False,
                    detail={"reason": reason, "scope": scope},
                )
                return command.block

        override = None
        if self.scope_policy is not None:
            override = self.scope_policy.permission_override(
                command.permission, scope
            )
        allowed = (
            override
            if override is not None
            else permission_manager.has_permission(user_id, command.permission)
        )
        if not allowed:
            reason = "权限不足"
            bus.dispatch(
                CommandRejected(
                    bot_id=getattr(event, "bot_id", ""),
                    self_id=getattr(event, "self_id", ""),
                    user_id=user_id,
                    group_id=group_id,
                    command_name=command.name,
                    reason=reason,
                )
            )
            audit_logger.record(
                "command.rejected",
                user_id,
                target=command.name,
                success=False,
                detail={"reason": reason, "scope": scope},
            )
            await event.reply(
                "【权限不足】该命令需要管理员权限，请联系群管理员"
            )
            return command.block

        bound_params: dict[str, Any] | None = None
        subcommand_name = ""
        if command.params or command.subcommands:
            parse_error = ""
            parse_target = ""
            if command.subcommands:
                subcommand_name, sub_args, parse_error = resolve_subcommand(
                    args, command.subcommands
                )
                if not parse_error:
                    sub = next(
                        (
                            item
                            for item in command.subcommands
                            if item.name == subcommand_name
                        ),
                        None,
                    )
                    params = sub.params if sub is not None else []
                    bound_params, parse_error = bind_params(sub_args, params)
                    parse_target = subcommand_name
            else:
                bound_params, parse_error = bind_params(args, command.params)
                parse_target = command.name
            if parse_error:
                reason = f"参数错误（{parse_target}）"
                bus.dispatch(
                    CommandRejected(
                        bot_id=getattr(event, "bot_id", ""),
                        self_id=getattr(event, "self_id", ""),
                        user_id=user_id,
                        group_id=group_id,
                        command_name=command.name,
                        reason=parse_error,
                    )
                )
                audit_logger.record(
                    "command.rejected",
                    user_id,
                    target=command.name,
                    success=False,
                    detail={"reason": parse_error, "scope": scope},
                )
                prefix = (self.command_start or ["/"])[0]
                usage_text = command.usage or build_usage(
                    command.name, command.params, command.subcommands
                )
                if usage_text.startswith("/"):
                    usage_text = prefix + usage_text[1:]
                await event.reply(
                    f"【参数错误】{parse_error}\n用法：{usage_text}"
                )
                return command.block

        context = CommandContext(
            command_name=command.name,
            args=args,
            plugin_name=command.plugin_name,
            permission=command.permission,
            feature_id=command.feature_id,
            scope=scope,
            connection_id=connection_id,
            subcommand=subcommand_name,
            params=bound_params,
            session=(
                self.session_manager.get(
                    str(getattr(event, "bot_id", "")),
                    group_id,
                    user_id,
                )
                if command.session and self.session_manager is not None
                else None
            ),
            trace_id=get_trace_id(),
            raw_event=event,
        )
        try:
            bus.dispatch(
                CommandInvoked(
                    bot_id=getattr(event, "bot_id", ""),
                    self_id=getattr(event, "self_id", ""),
                    user_id=user_id,
                    group_id=group_id,
                    command_name=command.name,
                    args=args,
                    plugin_name=command.plugin_name,
                )
            )
            await command.handler(event, Message(args), context)
            if self.stat_callback:
                await self.stat_callback(
                    user_id=user_id,
                    group_id=group_id or None,
                    command_name=command.name,
                    success=True,
                )
            audit_logger.record(
                "command.invoked",
                user_id,
                target=command.name,
                success=True,
            )
        except Exception as exc:
            logger.exception("command failed: %s", command.name)
            bus.dispatch(
                CommandFailed(
                    bot_id=getattr(event, "bot_id", ""),
                    self_id=getattr(event, "self_id", ""),
                    user_id=user_id,
                    group_id=group_id,
                    command_name=command.name,
                    error=str(exc),
                )
            )
            audit_logger.record(
                "command.failed",
                user_id,
                target=command.name,
                success=False,
                detail={"error": str(exc)},
            )
            if self.stat_callback:
                await self.stat_callback(
                    user_id=user_id,
                    group_id=group_id or None,
                    command_name=command.name,
                    success=False,
                )
            await event.reply("【×】命令执行失败，请稍后再试")
        return command.block

    def get_commands(self, plugin_name: str | None = None) -> list[Command]:
        commands = list(self._commands.values())
        if plugin_name:
            commands = [
                command
                for command in commands
                if command.plugin_name == plugin_name
            ]
        return sorted(
            {command.name: command for command in commands}.values(),
            key=lambda command: command.priority,
        )


command_registry = CommandRegistry()
