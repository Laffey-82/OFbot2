"""子进程插件沙箱 worker（process 模式）。

用法：python -m app.core.plugin_worker <plugin_dir> <config_json>

进程内加载插件模块并执行 `create_plugin()/setup()`，随后通过 stdin/stdout
换行 JSON-RPC 与父进程通信：
- 父进程请求 `handle`（命令/监听/任务统一按参数个数分派）、`ping`、`shutdown`；
- 插件通过 `RemoteContext` 代理访问框架能力，能力调用反向请求父进程执行。
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

from app.core.logger import get_logger
from app.core.messages import Message
from app.core.plugin import Plugin, PluginManifest
from app.core.plugin_ipc import message_from_plain

logger = get_logger(__name__)

_pending: dict[int, asyncio.Future[Any]] = {}
_counter = 0
_writer: Any = None
_SHUTDOWN: asyncio.Event | None = None


class RemoteEvent:
    """子进程内的事件代理：属性来自父进程序列化数据，reply 收集回传。"""

    def __init__(self, data: dict[str, Any], reply_cb) -> None:
        self._reply_cb = reply_cb
        self.__dict__.update(data or {})
        if "message" in (data or {}):
            self.message = message_from_plain(data.get("message"))

    async def reply(self, message: str | Message) -> None:
        text = str(message)
        await self._reply_cb(text)


class RemoteCommandContext:
    """命令上下文代理：暴露序列化字段与框架能力服务。"""

    def __init__(self, data: dict[str, Any]) -> None:
        self.__dict__.update(data or {})

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        return RemoteService(name)


class RemoteService:
    """框架能力服务代理：方法调用反向请求父进程执行。"""

    def __init__(self, name: str) -> None:
        self._service = name

    def __getattr__(self, method: str) -> _RemoteCall:
        if method.startswith("_"):
            raise AttributeError(method)
        return _RemoteCall(self._service, method)


class _RemoteCall:
    def __init__(self, service: str, method: str) -> None:
        self._service = service
        self._method = method

    async def __call__(self, *args: Any) -> Any:
        return _to_proxy(
            await _send_capability(self._service, self._method, args)
        )


class AttrDict(dict):
    """dict 属性访问代理：保持插件对内联模式返回值（对象属性）的兼容。"""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


def _to_proxy(value: Any) -> Any:
    if isinstance(value, dict):
        return AttrDict({key: _to_proxy(item) for key, item in value.items()})
    if isinstance(value, list):
        return [_to_proxy(item) for item in value]
    return value


class RemoteContext:
    """PluginContext 代理：能力访问反向 RPC，动态订阅等逃生通道显式拒绝。"""

    def __init__(self, *, name: str, config: dict[str, Any]) -> None:
        self.name = name
        self.config = config

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        if name == "subscribe":
            def subscribe(*args: Any, **kwargs: Any) -> Any:
                raise NotImplementedError(
                    "process 沙箱插件请使用 plugin.json features 声明监听器，"
                    "不支持运行时 ctx.subscribe"
                )

            return subscribe
        return RemoteService(name)


async def _send_capability(service: str, method: str, args: tuple) -> Any:
    global _counter
    _counter += 1
    msg_id = _counter
    loop = asyncio.get_running_loop()
    future: asyncio.Future[Any] = loop.create_future()
    _pending[msg_id] = future
    line = json.dumps(
        {
            "id": msg_id,
            "method": "capability",
            "params": {"service": service, "method": method, "args": _plain(args)},
        },
        ensure_ascii=False,
    )
    _send_line(line)
    try:
        return await asyncio.wait_for(future, timeout=30.0)
    finally:
        _pending.pop(msg_id, None)


def _plain(args: tuple) -> list[Any]:
    from app.core.plugin_ipc import to_plain

    return to_plain(list(args))


async def _resolve_and_run(
    module: Any, params: dict[str, Any]
) -> dict[str, Any]:
    import inspect

    from app.core.plugin import PluginManager

    handler = PluginManager.resolve_dotted(module, params["handler"])
    raw_args = params.get("args", []) or []
    replies: list[str] = []

    async def reply_cb(text: str) -> None:
        replies.append(text)

    sig = inspect.signature(handler)
    needs_ctx = "ctx" in sig.parameters

    if len(raw_args) == 3:
        event = RemoteEvent(raw_args[0], reply_cb)
        args_msg = message_from_plain(raw_args[1])
        context = RemoteCommandContext(raw_args[2])
        if needs_ctx:
            await handler(event, args_msg, context, ctx=RemoteContext(name="", config={}))
        else:
            await handler(event, args_msg, context)
    elif len(raw_args) == 1:
        event = RemoteEvent(raw_args[0], reply_cb)
        if needs_ctx:
            await handler(event, ctx=RemoteContext(name="", config={}))
        else:
            await handler(event)
    else:
        if needs_ctx:
            await handler(ctx=RemoteContext(name="", config={}))
        else:
            await handler()
    return {"replies": replies}


async def _serve(msg: dict[str, Any]) -> None:
    msg_id = msg.get("id")
    method = msg.get("method")
    params = msg.get("params", {})
    try:
        if method == "ping":
            result: Any = {"ok": True}
        elif method == "shutdown":
            result = {"ok": True}
        elif method == "handle":
            result = await _resolve_and_run(_MODULE, params)
        else:
            raise RuntimeError(f"未知方法: {method}")
        response = {"id": msg_id, "result": result}
    except Exception as exc:
        response = {"id": msg_id, "error": f"{type(exc).__name__}: {exc}"}
    _send_line(json.dumps(response, ensure_ascii=False))
    if method == "shutdown":
        if _SHUTDOWN is not None:
            _SHUTDOWN.set()


def _send_line(payload: str) -> None:
    """同步写入一行 JSON 并立即 flush（子进程 stdout 无 asyncio StreamWriter）。"""
    sys.stdout.buffer.write((payload + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


async def _read_loop() -> None:
    loop = asyncio.get_running_loop()
    while True:
        raw = await loop.run_in_executor(None, sys.stdin.readline)
        if not raw:
            break
        try:
            msg = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("worker: malformed JSON from parent: %s", exc)
            continue
        if "result" in msg or "error" in msg:
            future = _pending.pop(msg.get("id"), None)
            if future is not None and not future.done():
                if "error" in msg:
                    future.set_exception(RuntimeError(msg["error"]))
                else:
                    future.set_result(msg.get("result"))
        elif msg.get("method"):
            asyncio.create_task(_serve(msg))


_MODULE: Any = None


def _load_plugin(plugin_dir: Path) -> tuple[Any, Plugin, PluginManifest]:
    manifest = PluginManifest.model_validate_json(
        (plugin_dir / "plugin.json").read_text(encoding="utf-8")
    )
    module_name = f"plugins.{manifest.name}"
    spec = importlib.util.spec_from_file_location(
        module_name, plugin_dir / "__init__.py"
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load plugin module: {manifest.name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    factory = getattr(module, manifest.entry, None)
    if factory is None:
        raise ValueError(f"plugin entry {manifest.entry} not found")
    instance = factory()
    if not isinstance(instance, Plugin):
        raise TypeError("plugin entry must return a Plugin instance")
    instance.name = manifest.name
    instance.version = manifest.version
    return module, instance, manifest


async def main() -> int:
    global _writer, _MODULE, _SHUTDOWN
    if len(sys.argv) != 3:
        print("用法: python -m app.core.plugin_worker <plugin_dir> <config_json>")
        return 2
    plugin_dir = Path(sys.argv[1])
    config = json.loads(sys.argv[2] or "{}")
    _MODULE, instance, manifest = _load_plugin(plugin_dir)
    ctx = RemoteContext(name=manifest.name, config=config)
    instance.setup(ctx)
    loop = asyncio.get_running_loop()
    _writer = sys.stdout
    _SHUTDOWN = asyncio.Event()
    reader = loop.create_task(_read_loop())

    def _on_reader_done(task: asyncio.Task[Any]) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            _send_line(
                json.dumps(
                    {"method": "worker_error", "params": {"error": str(exc)}}
                )
            )

    reader.add_done_callback(_on_reader_done)
    try:
        await _SHUTDOWN.wait()
        reader.cancel()
        try:
            await reader
        except (asyncio.CancelledError, Exception):
            pass
    finally:
        for future in list(_pending.values()):
            if not future.done():
                future.cancel()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
