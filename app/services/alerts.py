from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete

from app.core.capabilities import Capability
from app.core.config import Settings, save_settings
from app.core.logger import get_logger
from app.db.base import session_factory
from app.db.models import AlertEvent

logger = get_logger(__name__)

BUILTIN_ALERT_TEMPLATES: list[dict[str, Any]] = [
    {
        "name": "连接断开",
        "event": "adapter_disconnected",
        "keyword": "",
        "description": "任一协议适配器断开连接时告警",
    },
    {
        "name": "任务失败",
        "event": "task.auto_disabled",
        "keyword": "",
        "description": "定时任务连续失败被自动停用时告警",
    },
    {
        "name": "流程失败",
        "event": "workflow.failed",
        "keyword": "",
        "description": "自动化流程运行失败时告警",
    },
    {
        "name": "CPU 过高",
        "event": "metric.cpu_high",
        "keyword": "",
        "description": "CPU 使用率超过配置阈值时告警",
    },
    {
        "name": "内存过高",
        "event": "metric.memory_high",
        "keyword": "",
        "description": "内存使用率超过配置阈值时告警",
    },
    {
        "name": "Agent 工具失败",
        "event": "agent.tool_failed",
        "keyword": "",
        "description": "Agent 工具调用失败时告警",
    },
]


def install_alert_template(service: AlertService, name: str) -> bool:
    """按模板创建规则（已存在同名规则时跳过），返回是否新建。"""
    template = next(
        (item for item in BUILTIN_ALERT_TEMPLATES if item["name"] == name),
        None,
    )
    if template is None:
        raise KeyError(f"告警模板不存在：{name}")
    if any(rule.name == name for rule in service.rules):
        return False
    service.add_rule(
        name=str(template["name"]),
        event=str(template["event"]),
        keyword=str(template["keyword"]),
    )
    return True


def install_default_alerts(
    service: AlertService, names: list[str] | None = None
) -> int:
    """安装指定（或全部）内置告警模板，返回新建数量。"""
    targets = names or [item["name"] for item in BUILTIN_ALERT_TEMPLATES]
    installed = 0
    for name in targets:
        try:
            if install_alert_template(service, name):
                installed += 1
        except KeyError:
            continue
    return installed


def persist_alert_rules(settings: Settings, service: Any) -> None:
    """将告警规则持久化到 settings.plugin_configs（供 Web / REST 使用）。"""
    settings.plugin_configs.setdefault("alerts", {})["rules"] = [
        {
            "name": rule.name,
            "event": rule.event,
            "target_group": rule.target_group,
            "target_private": getattr(rule, "target_private", ""),
            "enabled": rule.enabled,
            "keyword": rule.keyword,
            "min_interval_seconds": getattr(
                rule, "min_interval_seconds", 0
            ),
        }
        for rule in service.rules
    ]
    save_settings(settings)


class AlertRule:
    def __init__(
        self,
        name: str,
        event: str = "*",
        target_group: str = "",
        target_private: str = "",
        enabled: bool = True,
        keyword: str = "",
        min_interval_seconds: int = 0,
    ) -> None:
        self.name = name
        self.event = event
        self.target_group = target_group
        self.target_private = target_private
        self.enabled = enabled
        self.keyword = keyword
        self.min_interval_seconds = max(0, min_interval_seconds)

    @property
    def keywords(self) -> list[str]:
        return [item.strip() for item in self.keyword.split(",") if item.strip()]


class AlertService:
    def __init__(
        self,
        retention_days: int = 30,
        min_interval_seconds: int = 0,
    ) -> None:
        self.retention_days = max(1, retention_days)
        self.min_interval_seconds = max(0, min_interval_seconds)
        self.rules: list[AlertRule] = []
        self.notifier: Callable[[str, str], Any] | None = None
        self._last_notified: dict[tuple[str, str], float] = {}

    def add_rule(
        self,
        name: str,
        event: str = "*",
        target_group: str = "",
        target_private: str = "",
        keyword: str = "",
        min_interval_seconds: int = 0,
    ) -> None:
        self.rules.append(
            AlertRule(
                name,
                event,
                target_group,
                target_private=target_private,
                keyword=keyword,
                min_interval_seconds=min_interval_seconds,
            )
        )

    def remove_rule(self, name: str) -> bool:
        before = len(self.rules)
        self.rules = [rule for rule in self.rules if rule.name != name]
        return len(self.rules) != before

    def toggle_rule(self, name: str) -> bool:
        for rule in self.rules:
            if rule.name == name:
                rule.enabled = not rule.enabled
                return rule.enabled
        return False

    def set_notifier(self, func: Callable[[str, str], Any]) -> None:
        self.notifier = func

    async def check(self, event: str, detail: str = "") -> list[AlertRule]:
        try:
            async with session_factory()() as session:
                cutoff = datetime.now(UTC) - timedelta(
                    days=self.retention_days
                )
                await session.execute(
                    delete(AlertEvent).where(AlertEvent.created_at < cutoff)
                )
                await session.commit()
        except Exception:
            logger.exception("failed to prune alert history")
        triggered: list[AlertRule] = []
        for rule in self.rules:
            detail_match = (
                not rule.keywords
                or any(keyword in (detail or "") for keyword in rule.keywords)
            )
            if (
                rule.enabled
                and (rule.event == "*" or rule.event == event)
                and detail_match
            ):
                triggered.append(rule)
                try:
                    async with session_factory()() as session:
                        session.add(
                            AlertEvent(
                                rule_name=rule.name,
                                event=event,
                                detail=detail,
                            )
                        )
                        await session.commit()
                except Exception:
                    logger.exception("failed to persist alert event")
                if self.notifier:
                    key = (rule.name, event)
                    now = time.time()
                    last = self._last_notified.get(key, 0.0)
                    effective_interval = (
                        rule.min_interval_seconds
                        if rule.min_interval_seconds > 0
                        else self.min_interval_seconds
                    )
                    if (
                        effective_interval == 0
                        or now - last >= effective_interval
                    ):
                        self._last_notified[key] = now
                        await self.notifier(rule, detail)
        return triggered


def register_alert_capability() -> Capability:
    return Capability(
        name="alerts",
        description="告警规则与通知",
        methods=["add_rule", "check"],
    )
