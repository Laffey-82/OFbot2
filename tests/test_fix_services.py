from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.backup import BackupService
from app.services.doctor import run_environment_checks
from app.services.plugin_installer import PluginInstaller


def _manifest(**overrides: object) -> str:
    data = {
        "name": "testplug",
        "api_version": 1,
        "version": "1.0.0",
        "description": "test",
        "author": "",
        "dependencies": {},
    }
    data.update(overrides)
    return json.dumps(data)


class TestFlatZipInstall:
    def test_flat_zip_preserves_manifest(self) -> None:
        """扁平 zip（plugin.json 在根）安装后 manifest 存在且内容正确。"""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            plugins_dir = Path(tmp) / "plugins"
            installer = PluginInstaller(plugins_dir)
            archive = Path(tmp) / "flat.zip"
            manifest_json = _manifest(name="flatplug")
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("plugin.json", manifest_json)
                zf.writestr("__init__.py", "# flat plugin\n")
            installed = installer.install_zip(archive)
            assert (installed / "plugin.json").exists()
            content = json.loads((installed / "plugin.json").read_text(encoding="utf-8"))
            assert content["name"] == "flatplug"
            assert (installed / "__init__.py").exists()

    def test_nested_zip_still_works(self) -> None:
        """嵌套 zip（plugin.json 在子目录）安装后结构正确。"""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            plugins_dir = Path(tmp) / "plugins"
            installer = PluginInstaller(plugins_dir)
            archive = Path(tmp) / "nested.zip"
            manifest_json = _manifest(name="nestedplug")
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("nestedplug/plugin.json", manifest_json)
                zf.writestr("nestedplug/__init__.py", "# nested\n")
            installed = installer.install_zip(archive)
            assert (installed / "plugin.json").exists()
            assert (installed / "__init__.py").exists()

    def test_flat_zip_with_subdirs(self) -> None:
        """扁平 zip 含子目录条目时全部正确解压。"""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            plugins_dir = Path(tmp) / "plugins"
            installer = PluginInstaller(plugins_dir)
            archive = Path(tmp) / "flatdir.zip"
            manifest_json = _manifest(name="flatdir")
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("plugin.json", manifest_json)
                zf.writestr("__init__.py", "# init\n")
                zf.writestr("sub/module.py", "# module\n")
            installed = installer.install_zip(archive)
            assert (installed / "plugin.json").exists()
            assert (installed / "sub" / "module.py").exists()


class TestBackupSqlite:
    def test_create_backup_sqlite_uses_backup_api(self) -> None:
        """SQLite 数据库备份使用 sqlite3 backup API，备份后可用。"""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            backup_dir = Path(tmp) / "backups"
            svc = BackupService(backup_dir, keep=5)

            db_path = Path(tmp) / "test.db"
            conn = sqlite3.connect(str(db_path))
            conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, val TEXT)")
            conn.execute("INSERT INTO t VALUES (1, 'hello')")
            conn.commit()
            conn.close()

            result = svc.create_backup(db_path)
            backed_up = result / "test.db"
            assert backed_up.exists()

            verify = sqlite3.connect(str(backed_up))
            row = verify.execute("SELECT val FROM t WHERE id=1").fetchone()
            verify.close()
            assert row is not None
            assert row[0] == "hello"

    def test_create_backup_async(self) -> None:
        """create_backup_async 可在事件循环中调用。"""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            backup_dir = Path(tmp) / "backups"
            svc = BackupService(backup_dir, keep=5)
            src = Path(tmp) / "data.txt"
            src.write_text("async test", encoding="utf-8")

            async def run() -> Path:
                return await svc.create_backup_async(src)

            result = asyncio.run(run())
            assert (result / "data.txt").exists()
            assert (result / "data.txt").read_text(encoding="utf-8") == "async test"


class TestDoctorNoResidue:
    @pytest.mark.asyncio
    async def test_doctor_does_not_create_config(self) -> None:
        """doctor 自检不创建空 config.yaml 残留文件。"""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            config_path = root / "config.yaml"
            assert not config_path.exists()

            settings = SimpleNamespace(
                config_path=str(config_path),
                database_url=f"sqlite+aiosqlite:///{root.as_posix()}/test.db",
                plugins={},
                transport=SimpleNamespace(
                    protocol="onebot",
                    onebot=SimpleNamespace(mode="ws", enabled=False),
                ),
                web=SimpleNamespace(port=18080),
            )

            from app.db.base import get_engine, init_db, reset_db_engine

            await reset_db_engine()
            engine = get_engine(settings.database_url)
            await init_db(settings.database_url)

            await run_environment_checks(settings, app_state=None, root=root)

            assert not config_path.exists(), "doctor 不应创建 config.yaml"

            await engine.dispose()
            await reset_db_engine()

    @pytest.mark.asyncio
    async def test_doctor_port_check_accurate(self) -> None:
        """端口检查结果描述准确：空闲端口不误报为已监听。"""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            settings = SimpleNamespace(
                config_path=str(root / "config.yaml"),
                database_url=f"sqlite+aiosqlite:///{root.as_posix()}/test.db",
                plugins={},
                transport=SimpleNamespace(
                    protocol="onebot",
                    onebot=SimpleNamespace(mode="ws", enabled=False),
                ),
                web=SimpleNamespace(port=19999),
            )

            from app.db.base import get_engine, init_db, reset_db_engine

            await reset_db_engine()
            engine = get_engine(settings.database_url)
            await init_db(settings.database_url)

            checks = await run_environment_checks(settings, app_state=None, root=root)
            by_name = {item["name"]: item for item in checks}
            port_check = by_name.get("Web 端口")
            assert port_check is not None
            assert "空闲" in port_check["detail"]

            await engine.dispose()
            await reset_db_engine()
