"""监听环境作用域策略：逐群 / 私聊的功能开关、权限覆盖、黑名单与账号绑定。"""

from __future__ import annotations

from typing import Any

from app.core.config import RuntimeSettings, ScopeEntry, Settings
from app.core.logger import get_logger

logger = get_logger(__name__)

SCOPE_PRIVATE = "private:*"
SCOPE_GLOBAL_GROUP = "group:*"


def scope_for_group(group_id: Any) -> str:
    return f"group:{group_id}"


def resolve_scope(group_id: Any) -> str:
    """群消息 → group:<id>；私聊/未知 → private:*。"""
    if group_id:
        return scope_for_group(group_id)
    return SCOPE_PRIVATE


def feature_key(plugin: str, feature_id: str) -> str:
    return f"{plugin}.{feature_id}" if feature_id else plugin


class ScopePolicyService:
    """配置存于 settings.runtime.scopes，修改后调用方 save_settings 持久化即可即时生效。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings: Settings | None = settings
        self.runtime: RuntimeSettings = settings.runtime if settings else RuntimeSettings()
        self.ensure_defaults()

    def persist(self) -> None:
        """将包含当前 runtime.scopes 变更的 Settings 写回磁盘。"""
        if self._settings is None:
            return
        from app.core.config import save_settings

        save_settings(self._settings)

    def reload(self, settings: Settings) -> None:
        self.runtime = settings.runtime
        self.ensure_defaults()

    def ensure_defaults(self) -> None:
        for key in (SCOPE_GLOBAL_GROUP, SCOPE_PRIVATE):
            self.runtime.scopes.setdefault(key, ScopeEntry())

    def ensure_scope(self, scope: str) -> ScopeEntry:
        if not scope:
            return ScopeEntry()
        self.ensure_defaults()
        return self.runtime.scopes.setdefault(scope, ScopeEntry())

    def _lookup(self, scope: str, field: str) -> Any | None:
        entry = self.runtime.scopes.get(scope)
        if entry is not None:
            value = getattr(entry, field, None)
            if value:
                return value
        if scope.startswith("group:"):
            fallback = self.runtime.scopes.get(SCOPE_GLOBAL_GROUP)
            if fallback is not None:
                value = getattr(fallback, field, None)
                if value:
                    return value
        return None

    def feature_value(self, scope: str, key: str) -> bool | None:
        features = self._lookup(scope, "features")
        if features is None:
            return None
        value = features.get(key)
        return value if isinstance(value, bool) else None

    def feature_enabled(
        self,
        plugin: str,
        feature_id: str,
        scope: str,
        default: bool = True,
    ) -> bool:
        key = feature_key(plugin, feature_id)
        value = self.feature_value(scope, key)
        return default if value is None else value

    def set_feature(self, scope: str, key: str, value: bool | None) -> None:
        entry = self.ensure_scope(scope)
        if value is None:
            entry.features.pop(key, None)
        else:
            entry.features[key] = bool(value)

    def permission_override(self, permission: str, scope: str) -> bool | None:
        permissions = self._lookup(scope, "permissions")
        if permissions is None:
            return None
        value = permissions.get(permission)
        return value if isinstance(value, bool) else None

    def set_permission(
        self, scope: str, permission: str, value: bool | None
    ) -> None:
        entry = self.ensure_scope(scope)
        if value is None:
            entry.permissions.pop(permission, None)
        else:
            entry.permissions[permission] = bool(value)

    def blocked_for(self, scope: str) -> set[str]:
        blocked = self._lookup(scope, "blocked_users")
        return {str(item) for item in (blocked or [])}

    def is_blocked(self, user_id: Any, scope: str) -> bool:
        return str(user_id) in self.blocked_for(scope)

    def add_blocked(self, scope: str, user_id: Any) -> bool:
        entry = self.ensure_scope(scope)
        user_id = str(user_id)
        if user_id in entry.blocked_users:
            return False
        entry.blocked_users.append(user_id)
        return True

    def remove_blocked(self, scope: str, user_id: Any) -> bool:
        entry = self.ensure_scope(scope)
        user_id = str(user_id)
        if user_id not in entry.blocked_users:
            return False
        entry.blocked_users.remove(user_id)
        return True

    def silent_deny(self, scope: str) -> bool:
        entry = self.runtime.scopes.get(scope)
        if entry is not None and entry.silent_deny:
            return True
        if scope.startswith("group:"):
            fallback = self.runtime.scopes.get(SCOPE_GLOBAL_GROUP)
            if fallback is not None and fallback.silent_deny:
                return True
        return False

    def set_silent_deny(self, scope: str, value: bool) -> None:
        entry = self.ensure_scope(scope)
        entry.silent_deny = bool(value)

    def connection_for(self, scope: str) -> str:
        value = self._lookup(scope, "connection")
        return str(value or "")

    def set_connection(self, scope: str, connection_id: str) -> None:
        entry = self.ensure_scope(scope)
        entry.connection = str(connection_id or "")

    def scope_keys(self) -> list[str]:
        self.ensure_defaults()
        return sorted(self.runtime.scopes)

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return {
            key: {
                "connection": entry.connection,
                "features": dict(entry.features),
                "permissions": dict(entry.permissions),
                "blocked_users": list(entry.blocked_users),
                "silent_deny": entry.silent_deny,
            }
            for key, entry in self.runtime.scopes.items()
        }
