from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import httpx
import pytest

from app.services.plugin_repo import PluginMeta, PluginRepoService


def _zip_bytes(name: str = "demo") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            f"{name}/plugin.json",
            json.dumps(
                {
                    "name": name,
                    "api_version": 1,
                    "version": "1.0.0",
                }
            ),
        )
        archive.writestr(f"{name}/__init__.py", b"pass\n")
    return buffer.getvalue()


def test_registry_metadata_parsed() -> None:
    meta = PluginMeta.model_validate(
        {
            "id": "demo",
            "name": "demo",
            "api_version": 1,
            "version": "1.0.0",
            "category": "general",
            "dependencies": {"records": ">=1"},
            "tags": ["general", "utility"],
            "released_at": "2026-08-27",
            "checksum": "abc",
            "zip_url": "https://example.com/demo.zip",
        }
    )
    assert meta.api_version == 1
    assert meta.dependencies == {"records": ">=1"}
    assert meta.tags == ["general", "utility"]
    assert meta.checksum == "abc"


def test_official_registry_has_25_plugins_with_checksum() -> None:
    repo_root = Path(__file__).resolve().parents[1] / "plugin-repo"
    registry_path = repo_root / "registry.json"
    assert registry_path.exists()
    data = json.loads(registry_path.read_text(encoding="utf-8"))
    plugins = data["plugins"]
    assert len(plugins) == 25
    for entry in plugins:
        assert entry["api_version"] == 1
        assert entry["checksum"]
        assert entry["tags"]


@pytest.mark.asyncio
async def test_install_rejects_checksum_mismatch() -> None:
    with pytest.MonkeyPatch.context() as _:
        import tempfile

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
            tmp = Path(tmp_dir)
            repo_dir = tmp / "plugin-repo"
            packages = repo_dir / "packages"
            packages.mkdir(parents=True)
            data = _zip_bytes()
            (packages / "demo.zip").write_bytes(data)
            registry = {
                "format_version": 1,
                "plugins": [
                    {
                        "id": "demo",
                        "name": "demo",
                        "version": "1.0.0",
                        "category": "general",
                        "checksum": "0" * 64,
                        "zip_url": str(packages / "demo.zip"),
                    }
                ],
            }
            (repo_dir / "registry.json").write_text(
                json.dumps(registry), encoding="utf-8"
            )
            service = PluginRepoService(tmp / "plugins", repo_dir)
            with pytest.raises(RuntimeError, match="校验失败"):
                await service.install("demo")


@pytest.mark.asyncio
async def test_install_accepts_matching_checksum() -> None:
    import tempfile

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        tmp = Path(tmp_dir)
        repo_dir = tmp / "plugin-repo"
        packages = repo_dir / "packages"
        packages.mkdir(parents=True)
        data = _zip_bytes()
        (packages / "demo.zip").write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        registry = {
            "format_version": 1,
            "plugins": [
                {
                    "id": "demo",
                    "name": "demo",
                    "version": "1.0.0",
                    "category": "general",
                    "checksum": digest,
                    "zip_url": str(packages / "demo.zip"),
                }
            ],
        }
        (repo_dir / "registry.json").write_text(
            json.dumps(registry), encoding="utf-8"
        )
        service = PluginRepoService(tmp / "plugins", repo_dir)
        installed = await service.install("demo")
        assert (installed / "plugin.json").exists()


@pytest.mark.asyncio
async def test_install_rejects_incompatible_api_version() -> None:
    import tempfile

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        tmp = Path(tmp_dir)
        repo_dir = tmp / "plugin-repo"
        packages = repo_dir / "packages"
        packages.mkdir(parents=True)
        data = _zip_bytes()
        (packages / "demo.zip").write_bytes(data)
        registry = {
            "format_version": 1,
            "plugins": [
                {
                    "id": "demo",
                    "name": "demo",
                    "version": "1.0.0",
                    "api_version": 2,
                    "category": "general",
                    "zip_url": str(packages / "demo.zip"),
                }
            ],
        }
        (repo_dir / "registry.json").write_text(
            json.dumps(registry), encoding="utf-8"
        )
        service = PluginRepoService(tmp / "plugins", repo_dir)
        with pytest.raises(RuntimeError, match="不受支持"):
            await service.install("demo")


@pytest.mark.asyncio
async def test_url_mode_checksum_verified() -> None:
    import tempfile

    data = _zip_bytes()
    digest = hashlib.sha256(data).hexdigest()
    registry = {
        "format_version": 1,
        "plugins": [
            {
                "id": "demo",
                "name": "demo",
                "version": "1.0.0",
                "checksum": digest,
                "zip_url": "https://example.com/demo.zip",
            }
        ],
    }
    registry_bytes = json.dumps(registry).encode("utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("registry.json"):
            return httpx.Response(200, content=registry_bytes)
        return httpx.Response(200, content=data)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        tmp = Path(tmp_dir)
        service = PluginRepoService(
            tmp / "plugins",
            tmp / "plugin-repo",
            repo_url="https://example.com/registry.json",
            client=client,
        )
        installed = await service.install("demo")
        assert (installed / "plugin.json").exists()
    await client.aclose()
