from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from app.core.logger import get_logger

logger = get_logger(__name__)


class Permission:
    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description


class Role:
    def __init__(self, name: str, permissions: Iterable[str] | None = None):
        self.name = name
        self.permissions = set(permissions or [])


@dataclass
class Principal:
    identifier: str
    role: str = "user"
    scopes: set[str] = field(default_factory=set)
    extra_permissions: set[str] = field(default_factory=set)


class PermissionManager:
    def __init__(self) -> None:
        self._permissions: dict[str, Permission] = {}
        self._roles: dict[str, Role] = {}
        self._principals: dict[str, Principal] = {}
        self._default_roles = {
            "user": Role("user"),
            "operator": Role("operator"),
            "admin": Role("admin"),
            "superadmin": Role("superadmin"),
        }
        self._roles.update(self._default_roles)
        self._register_builtin_permissions()

    def _register_builtin_permissions(self) -> None:
        for name in [
            "bot.message",
            "bot.command",
            "system.status",
            "system.restart",
            "system.shutdown",
            "plugin.manage",
            "task.manage",
            "user.manage",
            "config.manage",
            "audit.read",
            "export.run",
            "file.manage",
        ]:
            self.register_permission(name)
        self._roles["superadmin"].permissions.update(
            {
                "bot.message",
                "bot.command",
                "system.status",
                "system.restart",
                "system.shutdown",
                "plugin.manage",
                "task.manage",
                "user.manage",
                "config.manage",
                "audit.read",
                "export.run",
                "file.manage",
            }
        )
        self._roles["admin"].permissions.update(
            {
                "bot.message",
                "bot.command",
                "system.status",
                "task.manage",
                "user.manage",
                "audit.read",
                "export.run",
                "file.manage",
            }
        )
        self._roles["operator"].permissions.update(
            {"bot.message", "bot.command", "system.status"}
        )
        self._roles["user"].permissions.update({"bot.message", "bot.command"})

    def register_permission(self, name: str, description: str = "") -> Permission:
        perm = Permission(name, description)
        self._permissions[name] = perm
        return perm

    def get_permission(self, name: str) -> Permission | None:
        return self._permissions.get(name)

    def register_role(self, name: str, permissions: Iterable[str]) -> Role:
        role = Role(name, permissions)
        self._roles[name] = role
        return role

    def grant_role_permission(self, role: str, permission: str) -> None:
        self._roles.setdefault(role, Role(role)).permissions.add(permission)

    def upsert_principal(
        self,
        identifier: str,
        role: str = "user",
        scopes: Iterable[str] | None = None,
        extra_permissions: Iterable[str] | None = None,
    ) -> Principal:
        principal = Principal(
            identifier,
            role,
            set(scopes or []),
            set(extra_permissions or []),
        )
        self._principals[identifier] = principal
        return principal

    def apply_superusers(self, user_ids: Iterable[str]) -> None:
        """将给定 QQ 列表应用为超级管理员，移除不再在列表中的旧超级管理员。"""
        current = set(user_ids)
        for identifier in list(self._principals):
            if (
                self._principals[identifier].role == "superadmin"
                and identifier not in current
            ):
                self._principals.pop(identifier, None)
        for uid in current:
            self.upsert_principal(uid, role="superadmin", scopes={"*"})

    def get_principal(self, identifier: str) -> Principal:
        return self._principals.get(
            identifier, Principal(identifier, "user", set(), set())
        )

    def has_permission(
        self,
        identifier: str,
        permission: str,
        scope: str | None = None,
    ) -> bool:
        principal = self.get_principal(identifier)
        if principal.role == "superadmin":
            return scope is None or "*" in principal.scopes or scope in principal.scopes
        role = self._roles.get(principal.role, self._roles["user"])
        if permission in role.permissions or permission in principal.extra_permissions:
            if scope is None or "*" in principal.scopes or scope in principal.scopes:
                return True
        return False

    def require(
        self,
        identifier: str,
        permission: str,
        scope: str | None = None,
    ) -> bool:
        return self.has_permission(identifier, permission, scope)


permission_manager = PermissionManager()


def require_permission(permission: str, scope: str | None = None) -> Callable:
    def decorator(func: Callable) -> Callable:
        func.__required_permission__ = permission
        func.__required_scope__ = scope
        return func

    return decorator
