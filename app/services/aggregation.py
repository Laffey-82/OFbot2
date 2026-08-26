from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Any

from app.core.capabilities import Capability


class AggregationService:
    def group_by(self, items: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in items:
            grouped[str(item.get(key))].append(item)
        return dict(grouped)

    def sum(self, items: list[dict[str, Any]], key: str) -> float:
        return sum(float(item.get(key, 0) or 0) for item in items)

    def count(self, items: list[dict[str, Any]]) -> int:
        return len(items)

    def avg(self, items: list[dict[str, Any]], key: str) -> float:
        if not items:
            return 0.0
        return self.sum(items, key) / len(items)

    def filter_by_date(
        self,
        items: list[dict[str, Any]],
        date_key: str,
        start: date,
        end: date,
    ) -> list[dict[str, Any]]:
        result = []
        for item in items:
            value = item.get(date_key)
            if not value:
                continue
            parsed = datetime.fromisoformat(str(value)).date()
            if start <= parsed <= end:
                result.append(item)
        return result


def register_aggregation_capability() -> Capability:
    return Capability(
        name="aggregation",
        description="通用分组、求和、计数、平均与日期过滤",
        methods=["group_by", "sum", "count", "avg", "filter_by_date"],
    )

