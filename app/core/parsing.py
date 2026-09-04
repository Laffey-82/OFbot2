"""命令参数解析：声明式参数（类型/必填/默认/可选值）与子命令（分段命令）。

插件可在 plugin.json 的 commands[].params / commands[].subcommands 中声明，
框架负责分词、类型转换、校验并给出友好用法提示；无需在插件内手写字符串解析。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ParamSpec(BaseModel):
    """命令参数声明。"""

    name: str
    type: str = "string"  # string | int | float | bool | rest（贪婪字符串）
    required: bool = False
    default: Any = None
    description: str = ""
    choices: list[Any] = Field(default_factory=list)


class SubcommandSpec(BaseModel):
    """子命令（分段命令）声明。"""

    name: str
    aliases: list[str] = Field(default_factory=list)
    description: str = ""
    params: list[ParamSpec] = Field(default_factory=list)


_TRUE_TOKENS = {"true", "yes", "on", "1", "是", "开"}
_FALSE_TOKENS = {"false", "no", "off", "0", "否", "关"}


def tokenize_args(text: str) -> list[str]:
    """按空白分词，支持单引号/双引号包裹，反斜杠原样保留（Windows 路径安全）。"""
    if not text or not text.strip():
        return []
    tokens: list[str] = []
    current: list[str] = []
    in_single = False
    in_double = False
    for char in text:
        if char == "'" and not in_double:
            in_single = not in_single
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            continue
        if char.isspace() and not in_single and not in_double:
            if current:
                tokens.append("".join(current))
                current = []
            continue
        current.append(char)
    if in_single or in_double:
        # 未闭合引号：按普通空白分词（引号作为字面量），与旧行为一致
        return text.split()
    if current:
        tokens.append("".join(current))
    return tokens


def _coerce(token: str, param: ParamSpec) -> tuple[Any, str | None]:
    """按参数类型转换，失败返回 (None, 错误信息)。"""
    param_type = param.type.lower()
    if param_type == "int":
        try:
            return int(token), None
        except ValueError:
            return None, f"参数 {param.name} 需要整数（收到：{token}）"
    if param_type == "float":
        try:
            return float(token), None
        except ValueError:
            return None, f"参数 {param.name} 需要数字（收到：{token}）"
    if param_type == "bool":
        lowered = token.lower()
        if lowered in _TRUE_TOKENS:
            return True, None
        if lowered in _FALSE_TOKENS:
            return False, None
        return None, f"参数 {param.name} 需要 true/false（收到：{token}）"
    return token, None


def _validate_choices(value: Any, param: ParamSpec) -> str | None:
    if not param.choices:
        return None
    choices = {str(item) for item in param.choices}
    if str(value) not in choices:
        allowed = " / ".join(str(item) for item in param.choices)
        return f"参数 {param.name} 只能取：{allowed}（收到：{value}）"
    return None


def bind_params(
    raw: str, params: list[ParamSpec]
) -> tuple[dict[str, Any], str | None]:
    """把原始参数串绑定到参数声明。

    支持位置参数与 `key=value` 命名参数；返回 (绑定结果, 错误信息)。
    """
    tokens = tokenize_args(raw)
    bound: dict[str, Any] = {}
    named: dict[str, str] = {}
    unknown_named: list[str] = []
    positional: list[str] = []
    for token in tokens:
        if "=" in token and not token.startswith("="):
            key, _, value = token.partition("=")
            if any(param.name == key for param in params):
                named[key] = value
            else:
                unknown_named.append(key)
            continue
        positional.append(token)

    positional_iter = iter(positional)
    for param in params:
        if param.name in named:
            token = named[param.name]
        else:
            try:
                token = next(positional_iter)
            except StopIteration:
                if param.required:
                    return {}, f"缺少必填参数：{param.name}"
                bound[param.name] = param.default
                continue
        if param.type.lower() in {"rest", "greedy_string"}:
            rest_tokens = [token, *list(positional_iter)]
            bound[param.name] = " ".join(rest_tokens)
            break
        value, error = _coerce(token, param)
        if error:
            return {}, error
        choice_error = _validate_choices(value, param)
        if choice_error:
            return {}, choice_error
        bound[param.name] = value

    for param in params:
        if param.name not in bound and param.required:
            return {}, f"缺少必填参数：{param.name}"

    leftover = list(positional_iter)
    if leftover:
        return {}, f"多余参数：{' '.join(leftover)}"
    if unknown_named:
        return {}, f"未知参数：{'、'.join(unknown_named)}"
    return bound, None


def resolve_subcommand(
    raw: str, subcommands: list[SubcommandSpec]
) -> tuple[str | None, str, str | None]:
    """解析子命令（分段命令）。

    返回 (子命令名, 剩余参数串, 错误信息)；未匹配时给出可用子命令列表。
    """
    tokens = tokenize_args(raw)
    if not tokens:
        available = " / ".join(item.name for item in subcommands)
        return None, "", f"缺少子命令，可用：{available}"
    first = tokens[0].lower()

    def names_of(sub: SubcommandSpec) -> set[str]:
        return {sub.name.lower(), *(alias.lower() for alias in sub.aliases)}

    for sub in subcommands:
        if first in names_of(sub):
            rest = " ".join(tokens[1:])
            return sub.name, rest, None
    # 支持点分 token：/order.add.info → 子命令 add + 参数 info
    for sep in (".", "·"):
        if sep in tokens[0]:
            head, _, tail = tokens[0].partition(sep)
            for sub in subcommands:
                if head.lower() in names_of(sub):
                    rest = (tail + (" " + " ".join(tokens[1:]) if tokens[1:] else "")).strip()
                    return sub.name, rest, None
    available = " / ".join(item.name for item in subcommands)
    return None, "", f"未知子命令 {tokens[0]}，可用：{available}"


def format_param_hint(param: ParamSpec) -> str:
    """生成单个参数的用法片段，如 <群号> / [备注=无]。"""
    name = param.name
    if param.choices:
        choices = "|".join(str(item) for item in param.choices)
        token = f"{name}={choices}"
    elif param.type.lower() in {"rest", "greedy_string"}:
        token = f"{name}…"
    else:
        token = name
    if param.required:
        return f"<{token}>"
    if param.default is not None and param.default != "":
        return f"[{token}={param.default}]"
    return f"[{token}]"


def build_usage(command_name: str, params: list[ParamSpec], subcommands: list[SubcommandSpec]) -> str:
    """由声明自动生成用法文本（未提供 usage 时的兜底与展示用）。"""
    parts = [command_name]
    if subcommands:
        parts.append("<子命令>")
    parts.extend(format_param_hint(param) for param in params)
    return " ".join(parts)
