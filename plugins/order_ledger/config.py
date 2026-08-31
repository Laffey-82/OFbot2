"""插件配置：默认值 + 与运行时配置的深合并。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

DEFAULT_CONFIG: dict[str, Any] = {
    "commission_ratio": {
        "打手": 0.69,
        "接单人": 0.26,
        "OF": 0.0,
        "应急公款": 0.05,
    },
    "order_settings": {
        "overdue_days": 3,
        "no_take_remind_hours": 2,
        "page_size": 5,
    },
    "notify_groups": [],
    "weekly_start_day": 5,
    "archive": {"enabled": True, "months": 3},
    "tasks": {
        "no_take_remind": {"enabled": True},
        "daily_commission": {"enabled": True, "export": False},
        "weekly_commission": {"enabled": True},
        "monthly_archive": {"enabled": True},
    },
    "message_constants": {},
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def merged_config(raw: dict[str, Any] | None) -> dict[str, Any]:
    """将插件运行时配置合并到默认配置，保证字段完整。"""
    return _deep_merge(DEFAULT_CONFIG, raw or {})


def ratio_text(ratio: dict[str, float]) -> str:
    """生成「打手：69% …」文案，百分比取整显示。"""
    return "  ".join(
        f"{name}：{round(float(value) * 100)}%"
        for name, value in ratio.items()
    )
