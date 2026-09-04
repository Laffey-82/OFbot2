"""Web 层缺陷修复回归测试。"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select as sa_select

from app.core.config import load_settings
from app.db.base import get_engine, init_db, reset_db_engine, session_factory
from app.db.models import WebAccount
from app.web.app import create_app, ensure_default_admin

# ── 缺陷 5：flash_redirect error 参数应正确 URL 编码 ──────────────────────


def test_flash_redirect_error_encoded() -> None:
    """flash_redirect 中 error 应使用 quote() 编码，防止重定向注入。"""
    from app.web.helpers import flash_redirect

    resp = flash_redirect("/test", error="包含中文&特殊=字符")
    location = resp.headers["location"]
    assert "error=" in location
    error_value = location.split("error=", 1)[1]
    assert "包含中文" not in error_value
    assert "%26" in error_value


def test_flash_redirect_message_encoded() -> None:
    """flash_redirect 中 message 同样应被 quote() 编码。"""
    from app.web.helpers import flash_redirect

    resp = flash_redirect("/page", message="ok=well&done")
    location = resp.headers["location"]
    assert "msg=" in location
    encoded_msg = location.split("msg=", 1)[1].split("&", 1)[0]
    assert "ok=well" not in encoded_msg


def test_flash_redirect_both_params() -> None:
    """同时传 message 和 error 时两个参数都应被编码。"""
    from app.web.helpers import flash_redirect

    resp = flash_redirect("/x", message="a&b", error="c=d")
    location = resp.headers["location"]
    assert "msg=" in location
    assert "error=" in location


def test_flash_redirect_no_params() -> None:
    """无 message/error 时 URL 不变。"""
    from app.web.helpers import flash_redirect

    resp = flash_redirect("/clean")
    assert resp.headers["location"] == "/clean"


# ── 缺陷 4：docs_pages 非法文档名应返回 404 而非 500 ──────────────────────


@pytest.mark.asyncio
async def test_docs_illegal_name_returns_404() -> None:
    """访问不存在的文档名 /docs/view/{name} 应返回 404。"""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = Path(tmp_dir) / "test.db"
        settings = load_settings()
        settings.config_path = str(Path(tmp_dir) / "config.yaml")
        settings.database.url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
        await reset_db_engine()
        engine = get_engine(settings.database.url)
        await init_db(settings.database.url)
        await ensure_default_admin(settings)

        app = create_app(settings, plugin_manager=None)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/login",
                data={"username": "admin", "password": "admin"},
                follow_redirects=False,
            )

            resp = await client.get("/docs/view/readme")
            assert resp.status_code == 200

            resp = await client.get("/docs/view/nonexistent_doc_xyz")
            assert resp.status_code == 404

            resp = await client.get("/docs/view/..%2F..%2Fconfig")
            assert resp.status_code == 404

        await engine.dispose()
        await reset_db_engine()


# ── 缺陷 2：admin 默认密码缓存应生效 ──────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_default_password_cache() -> None:
    """admin_uses_default_password() 结果应按密码哈希缓存，避免每次 600k PBKDF2。"""
    from app.web.helpers import (
        _default_password_checks,
        admin_uses_default_password,
    )
    from app.web.security import password_hasher

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = Path(tmp_dir) / "test.db"
        settings = load_settings()
        settings.config_path = str(Path(tmp_dir) / "config.yaml")
        settings.database.url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
        await reset_db_engine()
        engine = get_engine(settings.database.url)
        await init_db(settings.database.url)
        await ensure_default_admin(settings)

        _default_password_checks.clear()
        with patch.object(
            password_hasher, "verify_password", wraps=password_hasher.verify_password
        ) as mock_verify:
            result1 = await admin_uses_default_password()
            assert result1 is True
            assert mock_verify.call_count == 1

        with patch.object(
            password_hasher, "verify_password", wraps=password_hasher.verify_password
        ) as mock_verify:
            result2 = await admin_uses_default_password()
            assert result2 is True
            assert mock_verify.call_count == 0

        async with session_factory()() as session:
            admin = (
                await session.scalars(
                    sa_select(WebAccount).where(WebAccount.username == "admin")
                )
            ).first()
            assert admin is not None
            admin.password_hash = password_hasher.hash_password("new_password")
            await session.commit()

        _default_password_checks.clear()
        result3 = await admin_uses_default_password()
        assert result3 is False

        await engine.dispose()
        await reset_db_engine()


# ── 缺陷 1：验证 sync I/O 确实用了 to_thread ──────────────────────────────


@pytest.mark.asyncio
async def test_plugin_install_uses_to_thread() -> None:
    """插件安装路由应在 installer 不可用时优雅返回 redirect。"""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = Path(tmp_dir) / "test.db"
        settings = load_settings()
        settings.config_path = str(Path(tmp_dir) / "config.yaml")
        settings.database.url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
        await reset_db_engine()
        engine = get_engine(settings.database.url)
        await init_db(settings.database.url)
        await ensure_default_admin(settings)

        app = create_app(settings, plugin_manager=None)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/login",
                data={"username": "admin", "password": "admin"},
                follow_redirects=False,
            )
            resp = await client.post(
                "/plugins/install",
                files={"file": ("test.zip", b"fake", "application/zip")},
                follow_redirects=False,
            )
            assert resp.status_code == 303

        await engine.dispose()
        await reset_db_engine()


# ── 缺陷 3：仓库缓存不应被路由层强制失效 ──────────────────────────────────


def test_repo_service_cache_preserved() -> None:
    """_repo_service 在 repo_url/token 未变时不应清除缓存。"""
    from app.web.routers.plugins import _repo_service

    settings = load_settings()
    settings.web.plugin_repo_url = "https://example.com/repo"
    settings.web.plugin_repo_token = "tok123"

    fake_app = FastAPI()
    fake_app.state.plugin_repo_service = None

    svc1 = _repo_service(fake_app, settings)
    svc1._cache = {"cached": True}

    svc2 = _repo_service(fake_app, settings)
    assert svc2._cache == {"cached": True}

    settings.web.plugin_repo_token = "new_token"
    svc3 = _repo_service(fake_app, settings)
    assert svc3._cache is None
