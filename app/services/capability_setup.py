from __future__ import annotations

from app.core.capabilities import Capability, capability_registry


def register_builtin_capabilities() -> None:
    from app.services.aggregation import register_aggregation_capability
    from app.services.ai import register_ai_capability
    from app.services.alerts import register_alert_capability
    from app.services.audit_service import register_audit_capability
    from app.services.records import register_record_capability
    from app.services.state_machine import register_state_machine_capability
    from app.services.webhook import register_webhook_capability
    from app.services.workflow import register_workflow_capability

    for capability in [
        register_record_capability(),
        register_state_machine_capability(),
        register_aggregation_capability(),
        register_audit_capability(),
        register_ai_capability(),
        register_workflow_capability(),
        register_webhook_capability(),
        register_alert_capability(),
        Capability(name="export", description="导出 CSV/JSON/Excel/DOCX"),
        Capability(name="scheduler", description="定时任务与后台调度"),
        Capability(name="storage", description="带 TTL 的缓存存储"),
        Capability(name="files", description="文件上传与安全路径管理"),
    ]:
        capability_registry.register(capability)

