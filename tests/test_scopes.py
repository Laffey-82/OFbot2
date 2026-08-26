from __future__ import annotations

from app.core.config import RuntimeSettings, ScopeEntry, Settings
from app.core.scopes import (
    SCOPE_GLOBAL_GROUP,
    SCOPE_PRIVATE,
    ScopePolicyService,
    resolve_scope,
    scope_for_group,
)


def _policy() -> ScopePolicyService:
    settings = Settings()
    settings.runtime = RuntimeSettings(
        scopes={
            SCOPE_GLOBAL_GROUP: ScopeEntry(
                features={"dice.roll": True},
                blocked_users=["9"],
            ),
            SCOPE_PRIVATE: ScopeEntry(features={"dice.roll": False}),
        }
    )
    return ScopePolicyService(settings)


def test_resolve_scope() -> None:
    assert resolve_scope("123") == "group:123"
    assert scope_for_group(123) == "group:123"
    assert resolve_scope("") == SCOPE_PRIVATE
    assert resolve_scope(None) == SCOPE_PRIVATE


def test_feature_precedence() -> None:
    policy = _policy()
    assert policy.feature_enabled("dice", "roll", "group:123") is True  # group:* 覆盖
    policy.set_feature("group:456", "dice.roll", False)
    assert policy.feature_enabled("dice", "roll", "group:456") is False
    assert policy.feature_enabled("dice", "roll", SCOPE_PRIVATE) is False
    assert policy.feature_enabled("dice", "roll", "unknown") is True  # 默认开
    assert (
        policy.feature_enabled("dice", "roll", "group:456", default=False)
        is False
    )
    policy.set_feature("group:456", "dice.roll", None)
    assert policy.feature_enabled("dice", "roll", "group:456") is True


def test_permission_override_and_blocked() -> None:
    policy = _policy()
    assert policy.permission_override("system.restart", "group:1") is None
    policy.set_permission("group:1", "system.restart", False)
    assert policy.permission_override("system.restart", "group:1") is False
    assert policy.is_blocked("9", "group:1") is True  # group:* 回退
    assert policy.is_blocked("8", "group:1") is False
    policy.add_blocked("group:1", "8")
    assert policy.is_blocked("8", "group:1") is True
    assert policy.remove_blocked("group:1", "8") is True
    assert policy.is_blocked("8", "group:1") is False


def test_silent_deny_and_connection() -> None:
    policy = _policy()
    assert policy.silent_deny("group:1") is False
    policy.set_silent_deny(SCOPE_GLOBAL_GROUP, True)
    assert policy.silent_deny("group:1") is True
    policy.set_connection("group:1", "napcat_main")
    assert policy.connection_for("group:1") == "napcat_main"


def test_legacy_blocked_seed() -> None:
    from tempfile import NamedTemporaryFile

    import yaml

    from app.core.config import load_settings

    with NamedTemporaryFile(
        "w", suffix=".yaml", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(
            yaml.safe_dump(
                {"security": {"blocked_users": ["1", "2"]}},
                allow_unicode=True,
            )
        )
        path = tmp.name
    try:
        settings = load_settings(path)
        assert "1" in settings.runtime.scopes["group:*"].blocked_users
        assert "2" in settings.runtime.scopes["group:*"].blocked_users
    finally:
        import os

        os.unlink(path)
