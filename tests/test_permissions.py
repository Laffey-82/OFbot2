from app.core.permissions import permission_manager


def test_role_permission_and_scope() -> None:
    permission_manager.upsert_principal(
        "admin-1", role="admin", scopes={"group:1"}
    )
    assert permission_manager.has_permission("admin-1", "task.manage", "group:1")
    assert not permission_manager.has_permission("admin-1", "task.manage", "group:2")


def test_superadmin_has_plugin_manage() -> None:
    permission_manager.upsert_principal("super-1", role="superadmin", scopes={"*"})
    assert permission_manager.has_permission("super-1", "plugin.manage")


def test_superadmin_can_run_plugin_permission_command() -> None:
    permission_manager.upsert_principal("super-2", role="superadmin", scopes={"*"})
    assert permission_manager.has_permission("super-2", "template.ping")
