from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.services.backup import BackupService
from app.services.records import FieldSchema, RecordTypeSchema
from app.web.export_jobs import sanitize_export_name
from app.web.security import PasswordHasher, password_hasher


def test_backup_resolve_rejects_sibling_prefix_traversal() -> None:
    """startswith 前缀混淆穿越应被拒绝（回归）。"""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        root = Path(tmp_dir)
        backups = root / "backups"
        backups.mkdir()
        evil = root / "backups2"
        evil.mkdir()
        service = BackupService(backups)
        with pytest.raises(ValueError):
            service.resolve_backup("../backups2")
        with pytest.raises(ValueError):
            service.resolve_backup("..")
        # 合法备份仍可解析
        valid = backups / "20260101_000000"
        valid.mkdir()
        assert service.resolve_backup("20260101_000000") == valid


def test_export_name_sanitized() -> None:
    assert sanitize_export_name("order") == "order"
    assert sanitize_export_name("../etc/passwd") == "etc_passwd"
    assert sanitize_export_name("a b/c") == "a_b_c"
    assert sanitize_export_name("..") == "export"
    assert sanitize_export_name("x" * 200)[-3:] == "xxx"


def test_record_schema_name_validation() -> None:
    with pytest.raises(ValueError):
        RecordTypeSchema("../x", [])
    with pytest.raises(ValueError):
        RecordTypeSchema("a\\b", [])
    with pytest.raises(ValueError):
        FieldSchema("a/b", "string")
    with pytest.raises(ValueError):
        FieldSchema("", "string")
    RecordTypeSchema("order", [FieldSchema("amount", "number")])


def test_password_hash_iterations_and_legacy_compat() -> None:
    hasher = PasswordHasher()
    encoded = hasher.hash_password("secret")
    assert encoded.startswith("pbkdf2_sha256$600000$")
    assert hasher.verify_password("secret", encoded) is True
    assert hasher.verify_password("wrong", encoded) is False
    assert hasher.needs_upgrade(encoded) is False

    # 旧 200k 哈希仍可验证，且标记需要升级
    import hashlib
    import secrets

    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", b"secret", salt, 200_000)
    legacy = f"pbkdf2_sha256$200000${salt.hex()}${digest.hex()}"
    assert password_hasher.verify_password("secret", legacy) is True
    assert password_hasher.needs_upgrade(legacy) is True


@pytest.mark.asyncio
async def test_docs_raw_endpoint_removed() -> None:
    import tempfile

    from httpx import ASGITransport, AsyncClient

    from app.core.config import load_settings
    from app.db.base import get_engine, init_db, reset_db_engine
    from app.web.app import create_app

    settings = load_settings()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        settings.database.url = (
            f"sqlite+aiosqlite:///{(Path(tmp_dir) / 'w.db').as_posix()}"
        )
        await reset_db_engine()
        get_engine(settings.database.url)
        await init_db(settings.database.url)
        app = create_app(settings)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t"
        ) as client:
            raw = await client.get("/docs/readme")
            assert raw.status_code == 404
            view = await client.get("/docs/view/readme")
            assert view.status_code in (302, 303)
        await get_engine(settings.database.url).dispose()
        await reset_db_engine()
