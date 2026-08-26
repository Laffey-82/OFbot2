from __future__ import annotations

from app.core.parsing import (
    ParamSpec,
    SubcommandSpec,
    bind_params,
    build_usage,
    format_param_hint,
    resolve_subcommand,
    tokenize_args,
)


def test_tokenize_quotes() -> None:
    assert tokenize_args("") == []
    assert tokenize_args("  ") == []
    assert tokenize_args('a "b c" d') == ["a", "b c", "d"]
    assert tokenize_args("a 'b c'") == ["a", "b c"]
    # 未闭合引号降级为简单分词
    assert tokenize_args('a "b c') == ["a", '"b', "c"]


def test_bind_positional_and_named() -> None:
    params = [
        ParamSpec(name="group", type="string", required=True),
        ParamSpec(name="count", type="int", default=1),
        ParamSpec(name="force", type="bool", default=False),
    ]
    bound, error = bind_params("100 3 true", params)
    assert error is None
    assert bound == {"group": "100", "count": 3, "force": True}

    bound, error = bind_params("count=5 force=yes group=200", params)
    assert error is None
    assert bound == {"group": "200", "count": 5, "force": True}


def test_bind_errors() -> None:
    params = [ParamSpec(name="n", type="int", required=True)]
    _, error = bind_params("", params)
    assert error and "缺少必填参数" in error
    _, error = bind_params("abc", params)
    assert error and "需要整数" in error
    _, error = bind_params("1 extra", params)
    assert error and "多余参数" in error
    _, error = bind_params("n=1 nope=2", params)
    assert error and "未知参数" in error


def test_bind_choices_and_default() -> None:
    params = [
        ParamSpec(name="level", type="string", default="info", choices=["info", "debug"])
    ]
    bound, error = bind_params("debug", params)
    assert error is None and bound == {"level": "debug"}
    bound, error = bind_params("", params)
    assert error is None and bound == {"level": "info"}
    _, error = bind_params("warn", params)
    assert error and "只能取" in error


def test_resolve_subcommand() -> None:
    subs = [
        SubcommandSpec(name="hello", aliases=["你好"], params=[ParamSpec(name="name", default="世界")]),
        SubcommandSpec(name="world"),
    ]
    name, rest, error = resolve_subcommand("你好 小明", subs)
    assert name == "hello" and rest == "小明" and error is None
    name, rest, error = resolve_subcommand("world 3", subs)
    assert name == "world" and rest == "3"
    name, _, error = resolve_subcommand("", subs)
    assert name is None and error and "缺少子命令" in error
    name, _, error = resolve_subcommand("nope", subs)
    assert name is None and error and "未知子命令" in error


def test_usage_generation() -> None:
    params = [
        ParamSpec(name="group", type="string", required=True),
        ParamSpec(name="count", type="int", default=3),
    ]
    assert format_param_hint(params[0]) == "<group>"
    assert format_param_hint(params[1]) == "[count=3]"
    assert build_usage("greet", params, []) == "greet <group> [count=3]"
    assert build_usage(
        "greet", [], [SubcommandSpec(name="hello")]
    ) == "greet <子命令>"
