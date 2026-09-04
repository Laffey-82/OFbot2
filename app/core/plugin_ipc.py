"""子进程插件沙箱：父进程侧的 JSON-RPC 桥与模块代理。

process 模式的插件在独立子进程中加载执行：
- 父进程按 manifest 声明式注册命令/任务/监听器，handler 通过 `RemoteModule`
  代理到子进程执行。
- 子进程内的 `RemoteContext` 通过双向 JSON-RPC（stdin/stdout 换行 JSON）调用
  父进程的框架能力；`sandbox_policy.allow_services` 控制可访问的服务白名单，
  越权能力直接拒绝。
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import sys
from pathlib import Path
from typing import Any

from app.core.logger import get_logger
from app.core.messages import Message, MessageSegment
from app.core.plugin import Plugin

logger = get_logger(__name__)

_GATED_SERVICES = {"files", "export", "backup", "webhook", "ai"}


def to_plain(obj: Any) -> Any:
    """把事件/消息/上下文对象转换为 JSON 安全结构。"""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_plain(v) for v in obj]
    if isinstance(obj, Message):
        return {"__message__": [to_plain(s) for s in obj.segments]}
    if isinstance(obj, MessageSegment):
        return {"type": obj.type, "data": to_plain(obj.data)}
    model_dump = getattr(obj, "model_dump", None)
    if callable(model_dump):
        return to_plain(model_dump(mode="json"))
    if dataclasses.is_dataclass(obj):
        try:
            return {
                field.name: to_plain(getattr(obj, field.name))
                for field in dataclasses.fields(obj)
            }
        except Exception:
            return str(obj)
    if hasattr(obj, "__dict__"):
        try:
            return {
                key: to_plain(value)
                for key, value in vars(obj).items()
                if not key.startswith("_") and not callable(value)
            }
        except Exception:
            return str(obj)
    return str(obj)


def message_from_plain(data: Any) -> Message:
    """从 JSON 结构还原 Message。"""
    if data is None:
        return Message()
    if isinstance(data, str):
        return Message(data)
    if isinstance(data, dict) and "__message__" in data:
        segments = []
        for seg in data["__message__"] or []:
            if isinstance(seg, dict):
                segments.append(
                    MessageSegment(seg.get("type", "text"), seg.get("data", {}))
                )
        return Message(segments)
    return Message(str(data))


def check_sandbox_policy(manifest: Any, service: str) -> None:
    """校验沙箱插件是否被允许调用指定框架服务。"""
    if service not in _GATED_SERVICES:
        return
    policy = getattr(manifest, "sandbox_policy", None) or {}
    allowed = set(policy.get("allow_services", []) or [])
    if service not in allowed:
        raise PermissionError(
            f"sandbox 插件 {getattr(manifest, 'name', '?')} 调用能力 {service} "
            "未在 sandbox_policy.allow_services 中允许"
        )


class _RemoteNamespace:
    def __init__(self, bridge: PluginProcessBridge, prefix: str) -> None:
        self._bridge = bridge
        self._prefix = prefix

    def __getattr__(self, name: str) -> _RemoteHandler:
        if name.startswith("_"):
            raise AttributeError(name)
        return _RemoteHandler(self._bridge, f"{self._prefix}.{name}")


class _RemoteHandler:
    """代理到子进程的可调用 handler。"""

    def __init__(self, bridge: PluginProcessBridge, path: str) -> None:
        self._bridge = bridge
        self._path = path

    async def __call__(self, *args: Any) -> Any:
        result = await self._bridge.request(
            "handle", handler=self._path, args=to_plain(list(args))
        )
        event = args[0] if args else None
        for text in (result or {}).get("replies", []):
            reply = getattr(event, "reply", None)
            if reply is not None:
                try:
                    await reply(text)
                except Exception:
                    logger.warning(
                        "sandbox plugin reply failed: %s", self._path, exc_info=True
                    )
        return result


class RemotePluginModule:
    """process 插件在父进程中的模块代理。"""

    def __init__(self, bridge: PluginProcessBridge) -> None:
        self._bridge = bridge

    def __getattr__(self, name: str) -> _RemoteNamespace:
        if name.startswith("_"):
            raise AttributeError(name)
        return _RemoteNamespace(self._bridge, name)


class PluginProcessBridge:
    """管理插件子进程与 JSON-RPC 收发。"""

    def __init__(
        self,
        *,
        name: str,
        plugin_dir: str | Path,
        manifest: Any,
        config: dict[str, Any] | None,
        context: Any,
        request_timeout: float = 30.0,
    ) -> None:
        self.name = name
        self.plugin_dir = Path(plugin_dir)
        self.manifest = manifest
        self.config = config or {}
        self.context = context
        self.request_timeout = request_timeout
        self._proc: asyncio.subprocess.Process | None = None
        self._writer: Any = None
        self._reader_task: asyncio.Task[Any] | None = None
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._counter = 0
        self._closed = False

    async def start(self) -> None:
        root = Path(__file__).resolve().parents[2]
        self._proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "app.core.plugin_worker",
            str(self.plugin_dir),
            json.dumps(self.config, ensure_ascii=False),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=str(root),
        )
        assert self._proc.stdin is not None and self._proc.stdout is not None
        self._writer = self._proc.stdin
        self._reader_task = asyncio.create_task(
            self._read_loop(self._proc.stdout)
        )
        await self.request("ping", timeout=10.0)

    async def request(self, method: str, *, timeout: float | None = None, **params: Any) -> Any:
        if self._closed or self._proc is None or self._proc.returncode is not None:
            raise RuntimeError(f"sandbox 插件 {self.name} 子进程不可用")
        self._counter += 1
        msg_id = self._counter
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Any] = loop.create_future()
        self._pending[msg_id] = future
        line = json.dumps(
            {"id": msg_id, "method": method, "params": params},
            ensure_ascii=False,
        )
        try:
            self._writer.write((line + "\n").encode("utf-8"))
            await self._writer.drain()
            return await asyncio.wait_for(
                future, timeout or self.request_timeout
            )
        finally:
            self._pending.pop(msg_id, None)

    async def _read_loop(self, reader: asyncio.StreamReader) -> None:
        try:
            while True:
                raw = await reader.readline()
                if not raw:
                    break
                try:
                    msg = json.loads(raw.decode("utf-8", "replace"))
                except (json.JSONDecodeError, ValueError) as exc:
                    logger.warning("sandbox 插件 %s 收到无效 JSON: %s", self.name, exc)
                    continue
                if "result" in msg or "error" in msg:
                    future = self._pending.pop(msg.get("id"), None)
                    if future is not None and not future.done():
                        if "error" in msg:
                            future.set_exception(RuntimeError(msg["error"]))
                        else:
                            future.set_result(msg.get("result"))
                elif msg.get("method") == "capability":
                    asyncio.create_task(self._serve_capability(msg))
                elif msg.get("method") == "worker_error":
                    logger.warning(
                        "sandbox 插件 %s worker 报错: %s",
                        self.name,
                        msg.get("params", {}).get("error", ""),
                    )
        except (asyncio.CancelledError, ConnectionError, OSError):
            pass
        except Exception:
            logger.exception("sandbox 插件 %s 通信异常", self.name)
        finally:
            for future in list(self._pending.values()):
                if not future.done():
                    future.set_exception(
                        RuntimeError(f"sandbox 插件 {self.name} 子进程已退出")
                    )
            self._pending.clear()

    async def _serve_capability(self, msg: dict[str, Any]) -> None:
        msg_id = msg.get("id")
        params = msg.get("params", {})
        try:
            check_sandbox_policy(self.manifest, str(params.get("service", "")))
            service = getattr(self.context, params.get("service", ""), None)
            if service is None:
                raise RuntimeError(f"能力服务不存在: {params.get('service')}")
            method = getattr(service, params.get("method", ""), None)
            if method is None or not callable(method):
                raise RuntimeError(
                    f"能力方法不存在: {params.get('service')}.{params.get('method')}"
                )
            result = method(*params.get("args", []))
            if hasattr(result, "__await__"):
                result = await result
            response = {"id": msg_id, "result": to_plain(result)}
        except Exception as exc:
            response = {"id": msg_id, "error": f"{type(exc).__name__}: {exc}"}
        try:
            self._writer.write(
                (json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8")
            )
            await self._writer.drain()
        except Exception:
            logger.warning("sandbox 插件 %s 能力响应失败", self.name)

    async def stop(self) -> None:
        if self._closed:
            return
        if self._proc is not None and self._proc.returncode is None:
            try:
                await self.request("shutdown", timeout=3.0)
            except Exception:
                pass
            try:
                self._proc.terminate()
                await asyncio.wait_for(self._proc.wait(), timeout=3.0)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
        self._closed = True
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):
                pass


class RemotePluginInstance(Plugin):
    """process 插件在父进程中的生命周期存根：start 时启动子进程。"""

    def __init__(self, bridge: PluginProcessBridge) -> None:
        self._bridge = bridge
        self._started = False

    async def start(self) -> None:
        if not self._started:
            await self._bridge.start()
            self._started = True

    async def stop(self) -> None:
        await self._bridge.stop()
