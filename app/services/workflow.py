from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.core.bus import get_bus
from app.core.capabilities import Capability
from app.core.events import WorkflowAutoDisabled, WorkflowRunFailed
from app.core.logger import get_logger
from app.db.base import session_factory
from app.db.models import Workflow, WorkflowRun

logger = get_logger(__name__)


class WorkflowEngine:
    def __init__(self, auto_disable_after_failures: int = 0) -> None:
        self.actions: dict[str, Callable[..., Any]] = {}
        self.triggers: dict[str, Callable[..., Any]] = {}
        self.auto_disable_after_failures = max(
            0, auto_disable_after_failures
        )

    def register_action(self, name: str, func: Callable[..., Any]) -> None:
        self.actions[name] = func

    def register_trigger(self, name: str, func: Callable[..., Any]) -> None:
        self.triggers[name] = func

    @staticmethod
    def _get_value(context: dict[str, Any], path: str) -> Any:
        current: Any = context
        for part in path.split("."):
            if not isinstance(current, dict):
                return None
            current = current.get(part)
        return current

    @classmethod
    def evaluate_condition(
        cls, context: dict[str, Any], condition: Any
    ) -> bool:
        """条件匹配：支持 list（全部 AND）、单 dict、或 {"match": "all|any", "conditions": [...]}。"""
        if condition is None:
            return True
        match_mode = "all"
        if isinstance(condition, dict) and isinstance(condition.get("conditions"), list):
            match_mode = str(condition.get("match", "all"))
            conditions = condition["conditions"]
        elif isinstance(condition, list):
            conditions = condition
        else:
            conditions = [condition]
        if match_mode not in {"all", "any"}:
            match_mode = "all"
        results: list[bool] = []
        for item in conditions:
            if not isinstance(item, dict):
                continue
            field = str(item.get("field", ""))
            op = str(item.get("op", "eq"))
            value = item.get("value")
            actual = cls._get_value(context, field)
            matched = False
            if op == "eq":
                matched = actual == value
            elif op == "ne":
                matched = actual != value
            elif op == "exists":
                matched = bool(value) == (actual is not None)
            elif op == "contains":
                matched = value in (actual or "")
            elif op == "in":
                matched = actual in (value or [])
            elif op == "gt":
                try:
                    matched = float(actual) > float(value)
                except (TypeError, ValueError):
                    matched = False
            elif op == "lt":
                try:
                    matched = float(actual) < float(value)
                except (TypeError, ValueError):
                    matched = False
            results.append(matched)
        if not results:
            return True
        return all(results) if match_mode == "all" else any(results)

    async def create(self, name: str, definition: dict[str, Any]) -> Workflow:
        async with session_factory()() as session:
            workflow = Workflow(name=name, definition=definition)
            session.add(workflow)
            await session.commit()
            await session.refresh(workflow)
        return workflow

    async def list(self) -> list[Workflow]:
        async with session_factory()() as session:
            return list((await session.scalars(select(Workflow))).all())

    async def get(self, workflow_id: int) -> Workflow | None:
        async with session_factory()() as session:
            return await session.get(Workflow, workflow_id)

    async def update(
        self, workflow_id: int, name: str | None = None, definition: dict[str, Any] | None = None
    ) -> Workflow | None:
        async with session_factory()() as session:
            workflow = await session.get(Workflow, workflow_id)
            if workflow is None:
                return None
            if name:
                workflow.name = name
            if definition is not None:
                workflow.definition = definition
            await session.commit()
            await session.refresh(workflow)
        return workflow

    async def list_runs(self, limit: int = 50) -> list[WorkflowRun]:
        async with session_factory()() as session:
            query = (
                select(WorkflowRun)
                .order_by(WorkflowRun.created_at.desc())
                .limit(limit)
            )
            return list((await session.scalars(query)).all())

    async def trigger(self, trigger_type: str, context: dict[str, Any] | None = None) -> list[WorkflowRun]:
        workflows = await self.list()
        runs: list[WorkflowRun] = []
        for workflow in workflows:
            if (
                workflow.enabled
                and workflow.definition.get("trigger", {}).get("type")
                == trigger_type
            ):
                runs.append(await self.execute(workflow.id, context))
        return runs

    async def execute(self, workflow_id: int, context: dict[str, Any] | None = None) -> WorkflowRun:
        async with session_factory()() as session:
            workflow = await session.get(Workflow, workflow_id)
            if workflow is None:
                raise KeyError(workflow_id)
            run = WorkflowRun(workflow_id=workflow.id, status="running")
            session.add(run)
            await session.commit()
            await session.refresh(run)

        if not workflow.enabled:
            async with session_factory()() as session:
                run = await session.get(WorkflowRun, run.id)
                if run is not None:
                    run.status = "skipped"
                    run.result = {"reason": "workflow disabled"}
                    await session.commit()
            return run

        context = context or {}
        result: dict[str, Any] = {"steps": []}
        try:
            condition = workflow.definition.get("condition")
            if not self.evaluate_condition(context, condition):
                status = "skipped"
                result["reason"] = "condition not matched"
                result["condition"] = condition
            else:
                for step in workflow.definition.get("steps", []):
                    action_name = step.get("action")
                    action = self.actions.get(action_name)
                    if action is None:
                        raise ValueError(f"action not registered: {action_name}")
                    step_started = time.monotonic()
                    output = action(context, **step.get("params", {}))
                    if hasattr(output, "__await__"):
                        output = await output
                    result["steps"].append(
                        {
                            "action": action_name,
                            "output": output,
                            "elapsed_ms": round(
                                (time.monotonic() - step_started) * 1000, 1
                            ),
                        }
                    )
                status = "succeeded"
        except Exception as exc:
            logger.exception("workflow failed: %s", workflow.name)
            status = "failed"
            result["error"] = str(exc)
            try:
                get_bus().dispatch(
                    WorkflowRunFailed(
                        workflow_id=workflow.id,
                        workflow_name=workflow.name,
                        run_id=run.id,
                        error=str(exc),
                    )
                )
            except RuntimeError:
                pass

        async with session_factory()() as session:
            run = await session.get(WorkflowRun, run.id)
            if run:
                run.status = status
                run.result = result
                await session.commit()
        if (
            status == "failed"
            and self.auto_disable_after_failures > 0
        ):
            async with session_factory()() as session:
                recent = (
                    await session.scalars(
                        select(WorkflowRun)
                        .where(WorkflowRun.workflow_id == workflow_id)
                        .order_by(WorkflowRun.created_at.desc())
                        .limit(self.auto_disable_after_failures)
                    )
                ).all()
                consecutive = 0
                for item in recent:
                    if item.status != "failed":
                        break
                    consecutive += 1
                if consecutive >= self.auto_disable_after_failures:
                    workflow = await session.get(Workflow, workflow_id)
                    if workflow is not None and workflow.enabled:
                        now_iso = datetime.now(UTC).isoformat(
                            timespec="seconds"
                        )
                        workflow.enabled = False
                        definition = dict(workflow.definition)
                        cycles = list(
                            definition.get("self_heal_cycles") or []
                        )
                        cycles.append(
                            {"disabled": now_iso, "reenabled": None}
                        )
                        definition["auto_disabled"] = {
                            "reason": f"连续失败 {consecutive} 次，已自动停用",
                            "at": now_iso,
                        }
                        # 仅保留最近 9 个周期，避免 definition 无限增长
                        definition["self_heal_cycles"] = cycles[-9:]
                        workflow.definition = definition
                        await session.commit()
                        try:
                            get_bus().dispatch(
                                WorkflowAutoDisabled(
                                    workflow_id=workflow.id,
                                    workflow_name=workflow.name,
                                    reason=(
                                        f"连续失败 {consecutive} 次，已自动停用"
                                    ),
                                )
                            )
                        except RuntimeError:
                            pass
                        logger.warning(
                            "workflow %s auto-disabled after %s consecutive failures",
                            workflow.name,
                            consecutive,
                        )
        return run

    async def dry_run(
        self, workflow_id: int, context: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """干跑：校验触发器/条件/步骤，不实际执行任何动作。"""
        workflow = await self.get(workflow_id)
        if workflow is None:
            raise KeyError(workflow_id)
        definition = workflow.definition
        errors: list[str] = []
        warnings: list[str] = []
        trigger = definition.get("trigger", {})
        trigger_type = str(trigger.get("type", ""))
        known_triggers = {
            "message",
            "schedule",
            "webhook",
            "alert",
            "command",
            "record_changed",
            "status_changed",
        }
        if not trigger_type:
            errors.append("缺少触发器（trigger.type）")
        elif trigger_type not in known_triggers:
            warnings.append(f"触发器类型 {trigger_type} 未内置，需插件注册")
        if trigger_type == "schedule" and not trigger.get("cron"):
            errors.append("定时触发器缺少 cron 表达式")

        context = context or {}
        try:
            condition_matched = self.evaluate_condition(
                context, definition.get("condition")
            )
        except Exception as exc:
            condition_matched = False
            errors.append(f"条件校验失败：{exc}")

        steps = definition.get("steps", [])
        if not steps:
            warnings.append("流程没有动作步骤")
        for index, step in enumerate(steps, start=1):
            action_name = step.get("action") if isinstance(step, dict) else None
            if not action_name:
                errors.append(f"第 {index} 步缺少 action")
                continue
            if action_name not in self.actions:
                errors.append(f"第 {index} 步动作 {action_name} 未注册")
            elif not isinstance(step.get("params"), dict):
                errors.append(f"第 {index} 步参数必须是对象")
        return {
            "workflow_id": workflow.id,
            "valid": not errors,
            "errors": errors,
            "warnings": warnings,
            "condition_matched": condition_matched,
            "would_run_steps": len(steps) if not errors else 0,
        }

    async def get_run(self, run_id: int) -> WorkflowRun | None:
        async with session_factory()() as session:
            return await session.get(WorkflowRun, run_id)

    async def delete_run(self, run_id: int) -> bool:
        async with session_factory()() as session:
            run = await session.get(WorkflowRun, run_id)
            if run is None:
                return False
            await session.delete(run)
            await session.commit()
        return True

    async def delete(self, workflow_id: int) -> bool:
        async with session_factory()() as session:
            workflow = await session.get(Workflow, workflow_id)
            if workflow is None:
                return False
            await session.delete(workflow)
            await session.commit()
        return True


def register_workflow_capability() -> Capability:
    return Capability(
        name="workflow",
        description="自动化流程引擎",
        methods=["create", "list", "execute", "register_action", "register_trigger"],
    )
