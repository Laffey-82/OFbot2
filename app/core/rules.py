"""声明式响应规则（NoneBot2 Rule 的轻量版）。

插件可在 plugin.json 的 commands[].rules / listeners[].rules 中声明规则，
框架在作用域门控之后、参数解析/处理器执行之前统一匹配；
插件亦可通过 ``ctx.rules.register(name, checker)`` 注册自定义规则。
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, Field

from app.core.logger import get_logger

logger = get_logger(__name__)

RuleChecker = Callable[[Any, dict[str, Any]], bool | Awaitable[bool]]


class RuleSpec(BaseModel):
    """规则声明：name 为内置或插件注册的规则名，params 为其参数。"""

    name: str
    params: dict[str, Any] = Field(default_factory=dict)


def _plain_text(event: Any) -> str:
    message = getattr(event, "message", None)
    if message is not None and hasattr(message, "extract_plain_text"):
        return message.extract_plain_text().strip()
    return str(getattr(event, "message", "") or "").strip()


def _is_private(event: Any) -> bool:
    return not getattr(event, "group_id", "")


async def _rule_to_me(event: Any, params: dict[str, Any]) -> bool:
    """to_me：被 @ 或私聊消息视为针对机器人。"""
    if _is_private(event):
        return True
    return bool(getattr(event, "at_self", False))


async def _rule_keyword(event: Any, params: dict[str, Any]) -> bool:
    """keyword：消息文本包含指定关键词（value 支持字符串或列表）。"""
    text = _plain_text(event)
    raw = params.get("value") or params.get("keyword")
    keywords = raw if isinstance(raw, list) else [str(raw or "")]
    return any(str(kw) in text for kw in keywords)


async def _rule_regex(event: Any, params: dict[str, Any]) -> bool:
    """regex：消息文本匹配正则表达式。"""
    pattern = params.get("value") or params.get("pattern")
    if not pattern:
        return False
    try:
        return re.search(str(pattern), _plain_text(event)) is not None
    except re.error:
        logger.warning("invalid rule regex: %s", pattern)
        return False


async def _rule_group_only(event: Any, params: dict[str, Any]) -> bool:
    return bool(getattr(event, "group_id", ""))


async def _rule_private_only(event: Any, params: dict[str, Any]) -> bool:
    return _is_private(event)


async def _rule_in_group(event: Any, params: dict[str, Any]) -> bool:
    """in_group：群号在白名单内（params.groups）。"""
    group_id = str(getattr(event, "group_id", "") or "")
    if not group_id:
        return False
    groups = params.get("groups") or params.get("value") or []
    if isinstance(groups, str):
        groups = [item.strip() for item in groups.split(",") if item.strip()]
    return group_id in {str(item) for item in groups}


BUILTIN_RULES: dict[str, RuleChecker] = {
    "to_me": _rule_to_me,
    "keyword": _rule_keyword,
    "regex": _rule_regex,
    "group_only": _rule_group_only,
    "private_only": _rule_private_only,
    "in_group": _rule_in_group,
}


class RuleRegistry:
    """规则注册表：内置规则 + 插件自定义规则，提供校验与匹配。"""

    def __init__(self) -> None:
        self._rules: dict[str, RuleChecker] = dict(BUILTIN_RULES)

    def register(self, name: str, checker: RuleChecker) -> None:
        if not callable(checker):
            raise TypeError(f"rule checker {name} must be callable")
        self._rules[name] = checker

    def unregister(self, name: str) -> None:
        if name in BUILTIN_RULES:
            raise ValueError(f"cannot unregister builtin rule: {name}")
        self._rules.pop(name, None)

    def names(self) -> list[str]:
        return sorted(self._rules)

    def has(self, name: str) -> bool:
        return name in self._rules

    def validate(self, rules: list[RuleSpec]) -> list[str]:
        """返回规则名中未注册的部分；空列表表示全部可用。"""
        return [rule.name for rule in rules if rule.name not in self._rules]

    async def check(
        self, rules: list[RuleSpec], event: Any
    ) -> tuple[bool, str | None]:
        """按声明顺序匹配所有规则；返回 (是否通过, 未通过原因)。"""
        for rule in rules:
            checker = self._rules.get(rule.name)
            if checker is None:
                return False, f"规则未注册：{rule.name}"
            try:
                result = checker(event, rule.params)
                if hasattr(result, "__await__"):
                    result = await result
            except Exception as exc:
                logger.warning(
                    "rule %s raised: %s", rule.name, exc
                )
                return False, f"规则 {rule.name} 执行异常"
            if not result:
                return False, f"rule.{rule.name}"
        return True, None


rule_registry = RuleRegistry()
