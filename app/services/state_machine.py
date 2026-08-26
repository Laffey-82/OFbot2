from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.core.bus import get_bus
from app.core.capabilities import Capability
from app.core.events import RecordStatusChanged


class Transition:
    def __init__(
        self,
        from_status: str,
        to_status: str,
        permission: str = "",
        before: Callable[..., Any] | None = None,
        after: Callable[..., Any] | None = None,
    ) -> None:
        self.from_status = from_status
        self.to_status = to_status
        self.permission = permission
        self.before = before
        self.after = after


class StateMachine:
    def __init__(self, name: str, initial: str = "active") -> None:
        self.name = name
        self.initial = initial
        self.transitions: list[Transition] = []

    def add(self, transition: Transition) -> None:
        self.transitions.append(transition)

    @property
    def states(self) -> list[str]:
        seen: list[str] = []
        for transition in self.transitions:
            for state in (transition.from_status, transition.to_status):
                if state and state not in seen:
                    seen.append(state)
        return seen

    def can(self, current: str, target: str, permission: str = "") -> bool:
        return any(
            t.from_status == current
            and t.to_status == target
            and (not t.permission or t.permission == permission)
            for t in self.transitions
        )


class StateMachineService:
    def __init__(self) -> None:
        self.machines: dict[str, StateMachine] = {}

    def register(self, machine: StateMachine) -> None:
        self.machines[machine.name] = machine

    def unregister(self, name: str) -> bool:
        return self.machines.pop(name, None) is not None

    def transition(
        self,
        machine_name: str,
        current: str,
        target: str,
        *,
        permission: str = "",
        context: dict[str, Any] | None = None,
    ) -> str:
        machine = self.machines[machine_name]
        if not machine.can(current, target, permission):
            raise ValueError(f"invalid transition: {current} -> {target}")
        transition = next(
            t
            for t in machine.transitions
            if t.from_status == current
            and t.to_status == target
            and (not t.permission or t.permission == permission)
        )
        if transition.before:
            transition.before(context or {})
        if transition.after:
            transition.after(context or {})
        try:
            get_bus().dispatch(
                RecordStatusChanged(
                    machine_name=machine_name,
                    from_status=current,
                    to_status=target,
                )
            )
        except RuntimeError:
            pass
        return target


def register_state_machine_capability() -> Capability:
    return Capability(
        name="state_machine",
        description="通用状态机与流转校验",
        methods=["register", "transition"],
    )
