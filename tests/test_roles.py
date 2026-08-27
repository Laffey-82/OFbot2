from __future__ import annotations

from app.core.config import RuntimeSettings, Settings
from app.core.permissions import PermissionManager


def test_user_roles_applied_to_permission_manager() -> None:
    settings = Settings()
    settings.runtime = RuntimeSettings(
        user_roles={
            "100": "admin",
            "200": "operator",
            "300": "superadmin",
        }
    )
    permissions = PermissionManager()
    for user_id, role in settings.runtime.user_roles.items():
        permissions.upsert_principal(
            str(user_id),
            role=str(role or "user"),
            scopes={"*"} if role == "superadmin" else set(),
        )
    assert permissions.has_permission("100", "task.manage") is True
    assert permissions.has_permission("100", "plugin.manage") is False
    assert permissions.has_permission("200", "system.status") is True
    assert permissions.has_permission("200", "task.manage") is False
    assert permissions.has_permission("300", "plugin.manage") is True
    assert permissions.has_permission("300", "config.manage") is True
    assert permissions.has_permission("999", "bot.command") is True  # 默认 user
