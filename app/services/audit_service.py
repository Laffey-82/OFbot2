from __future__ import annotations

from typing import Any

from app.core.capabilities import Capability
from app.core.security import audit_logger
from app.db.base import session_factory
from app.db.models import AuditLog


class AuditService:
    async def record(
        self,
        action: str,
        actor: str = "",
        *,
        target: str = "",
        success: bool = True,
        detail: dict[str, Any] | None = None,
    ) -> None:
        audit_logger.record(action, actor, target=target, success=success, detail=detail)
        try:
            async with session_factory()() as session:
                session.add(
                    AuditLog(
                        action=action,
                        actor=actor,
                        target=target,
                        success=success,
                        detail=detail or {},
                    )
                )
                await session.commit()
        except Exception:
            pass


def register_audit_capability() -> Capability:
    return Capability(
        name="audit",
        description="统一审计写入与查询",
        methods=["record"],
    )

