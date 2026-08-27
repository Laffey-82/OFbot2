"""插件仓库服务：从本仓库内置 plugin-repo/（本地模式）或远程注册表（URL 模式）读取并安装插件。"""

from __future__ import annotations

import hashlib
import json
import time
import zipfile
from pathlib import Path

import httpx
from pydantic import BaseModel

from app.core.http import make_http_client
from app.core.logger import get_logger
from app.services.plugin_installer import PluginInstaller

logger = get_logger(__name__)

_CACHE_TTL = 60.0


class PluginMeta(BaseModel):
    id: str
    name: str = ""
    api_version: int = 1
    version: str = ""
    description: str = ""
    author: str = ""
    category: str = ""
    dependencies: dict[str, str] = {}
    tags: list[str] = []
    released_at: str = ""
    checksum: str = ""
    zip_url: str = ""


class PluginRepoService:
    """双数据源插件仓库：repo_url 为空时扫描本地 plugin-repo/，否则拉取远程注册表。"""

    def __init__(
        self,
        plugins_dir: str | Path,
        repo_dir: str | Path,
        *,
        repo_url: str = "",
        token: str = "",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.plugins_dir = Path(plugins_dir)
        self.plugins_dir.mkdir(parents=True, exist_ok=True)
        self.repo_dir = Path(repo_dir)
        self.repo_url = (repo_url or "").strip()
        self.token = (token or "").strip()
        self._client = client
        self._own_client = client is None
        self._cache: list[PluginMeta] | None = None
        self._cache_at = 0.0

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = make_http_client(15.0)
        return self._client

    async def close(self) -> None:
        if self._own_client and self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None

    async def list_plugins(self, force_refresh: bool = False) -> list[PluginMeta]:
        if not force_refresh and self._cache is not None:
            if time.time() - self._cache_at < _CACHE_TTL:
                return self._cache
        if self.repo_url:
            plugins = await self._fetch_registry()
        else:
            plugins = self._scan_local()
        self._cache = plugins
        self._cache_at = time.time()
        return plugins

    async def _fetch_registry(self) -> list[PluginMeta]:
        headers = {}
        if self.token:
            headers["Authorization"] = f"token {self.token}"
        try:
            response = await self._http().get(self.repo_url, headers=headers)
        except Exception as exc:
            raise RuntimeError(f"插件仓库连接失败：{exc}") from exc
        if response.status_code == 401 or response.status_code == 403:
            raise RuntimeError(
                "插件仓库需要授权：请在配置中填写 plugin_repo_token，"
                "或改为本地目录模式（清空 plugin_repo_url）"
            )
        if response.status_code != 200:
            raise RuntimeError(
                f"插件仓库返回异常状态码：{response.status_code}"
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError("插件仓库注册表不是有效 JSON") from exc
        return [PluginMeta.model_validate(item) for item in data.get("plugins", [])]

    def _scan_local(self) -> list[PluginMeta]:
        registry_path = self.repo_dir / "registry.json"
        if registry_path.exists():
            try:
                data = json.loads(
                    registry_path.read_text(encoding="utf-8")
                )
                return [
                    PluginMeta.model_validate(item)
                    for item in data.get("plugins", [])
                ]
            except (ValueError, json.JSONDecodeError) as exc:
                logger.warning("plugin-repo registry 解析失败，回退扫描 zip：%s", exc)
        plugins: list[PluginMeta] = []
        if not (self.repo_dir / "packages").exists():
            return plugins
        for zip_path in sorted((self.repo_dir / "packages").glob("*.zip")):
            try:
                with zipfile.ZipFile(zip_path) as archive:
                    manifest_name = next(
                        name
                        for name in archive.namelist()
                        if name.endswith("plugin.json")
                    )
                    manifest = json.loads(
                        archive.read(manifest_name).decode("utf-8")
                    )
                plugin_id = str(manifest.get("name", zip_path.stem))
                plugins.append(
                    PluginMeta(
                        id=plugin_id,
                        name=plugin_id,
                        api_version=int(manifest.get("api_version", 1) or 1),
                        version=str(manifest.get("version", "")),
                        description=str(manifest.get("description", "")),
                        author=str(manifest.get("author", "")),
                        category="local",
                        dependencies={
                            str(key): str(value)
                            for key, value in (
                                manifest.get("dependencies", {}) or {}
                            ).items()
                        },
                        tags=[
                            str(item)
                            for item in (
                                manifest.get("tags", [])
                                or ["local"]
                            )
                        ],
                        zip_url=str(zip_path),
                    )
                )
            except Exception as exc:
                logger.warning("跳过无效插件包 %s：%s", zip_path.name, exc)
        return plugins

    async def get_plugin(self, plugin_id: str) -> PluginMeta:
        for plugin in await self.list_plugins():
            if plugin.id == plugin_id or plugin.name == plugin_id:
                return plugin
        raise KeyError(f"插件仓库中不存在：{plugin_id}")

    async def install(
        self,
        plugin_id: str,
        target_name: str | None = None,
        *,
        replace: bool = False,
    ) -> Path:
        meta = await self.get_plugin(plugin_id)
        if meta.zip_url.startswith(("http://", "https://")):
            archive = await self._download(meta.zip_url)
            if meta.checksum:
                digest = hashlib.sha256(archive.read_bytes()).hexdigest()
                if digest != meta.checksum.lower():
                    archive.unlink(missing_ok=True)
                    raise RuntimeError(
                        f"插件包校验失败（checksum 不匹配），已拒绝安装：{plugin_id}"
                    )
        else:
            archive = Path(meta.zip_url)
            if not archive.exists():
                raise FileNotFoundError(f"插件包不存在：{archive}")
            if meta.checksum:
                digest = hashlib.sha256(archive.read_bytes()).hexdigest()
                if digest != meta.checksum.lower():
                    raise RuntimeError(
                        f"插件包校验失败（checksum 不匹配）：{plugin_id}"
                    )
        if meta.api_version != 1:
            raise RuntimeError(
                f"插件 {plugin_id} api_version {meta.api_version} 不受支持"
            )
        install_name = target_name or meta.name
        target = self.plugins_dir / install_name
        if target.exists():
            if not replace:
                raise ValueError(f"插件已存在：{install_name}")
            self._trash(target)
        installed = PluginInstaller(self.plugins_dir).install_zip(archive)
        if target_name and target_name != installed.name:
            installed_path = self.plugins_dir / installed.name
            if installed_path.exists() and installed_path != target:
                installed_path.rename(target)
            installed = target
        return installed

    def installed_version(self, name: str) -> str | None:
        manifest_path = self.plugins_dir / name / "plugin.json"
        if not manifest_path.exists():
            return None
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            return str(data.get("version", "")) or None
        except (ValueError, json.JSONDecodeError):
            return None

    def _trash(self, target: Path) -> None:
        trash_dir = self.plugins_dir / ".trash"
        trash_dir.mkdir(parents=True, exist_ok=True)
        archived = trash_dir / f"{target.name}-{int(time.time())}"
        target.rename(archived)

    async def _download(self, url: str) -> Path:
        headers = {}
        if self.token:
            headers["Authorization"] = f"token {self.token}"
        try:
            response = await self._http().get(url, headers=headers)
        except Exception as exc:
            raise RuntimeError(f"插件包下载失败：{exc}") from exc
        if response.status_code != 200:
            raise RuntimeError(
                f"插件包下载失败（HTTP {response.status_code}）"
            )
        tmp_dir = self.plugins_dir.parent / ".plugin_repo_tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        target = tmp_dir / f"{int(time.time() * 1000)}.zip"
        target.write_bytes(response.content)
        return target
