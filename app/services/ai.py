from __future__ import annotations

import asyncio
import inspect
import json
import re
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.capabilities import Capability
from app.core.logger import get_logger

logger = get_logger(__name__)

_shared_client: httpx.AsyncClient | None = None
_shared_client_config: str = ""


def _get_shared_client(timeout: float = 60, config_key: str = "") -> httpx.AsyncClient:
    global _shared_client, _shared_client_config
    if _shared_client is not None and _shared_client_config == config_key:
        return _shared_client
    if _shared_client is not None:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_shared_client.aclose())
        except RuntimeError:
            pass
    _shared_client = httpx.AsyncClient(timeout=timeout)
    _shared_client_config = config_key
    return _shared_client


def _response_text(data: dict[str, Any], provider: str) -> str:
    """从 chat 响应中安全提取文本，choices 或 content 为空时抛 RuntimeError。"""
    try:
        if provider == "openai":
            choices = data.get("choices") or []
            if not choices:
                raise RuntimeError(f"OpenAI 响应缺少 choices: {data}")
            content = choices[0].get("message", {}).get("content")
            if not content:
                raise RuntimeError(f"OpenAI 响应 content 为空: {data}")
            return content
        if provider == "gemini":
            candidates = data.get("candidates") or []
            if not candidates:
                raise RuntimeError(f"Gemini 响应缺少 candidates: {data}")
            parts = candidates[0].get("content", {}).get("parts") or []
            if not parts or not parts[0].get("text"):
                raise RuntimeError(f"Gemini 响应 text 为空: {data}")
            return parts[0]["text"]
        if provider == "anthropic":
            content = data.get("content") or []
            if not content:
                raise RuntimeError(f"Anthropic 响应缺少 content: {data}")
            return "".join(block.get("text", "") for block in content)
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"解析 {provider} 响应失败: {exc}") from exc
    return ""


class AIServiceError(Exception):
    """AI 能力不可用或不支持时的明确错误。"""


class AIProvider:
    name = "base"
    supported_methods: frozenset[str] = frozenset({"chat"})

    async def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        raise NotImplementedError

    async def chat_response(
        self, messages: list[dict[str, str]], **kwargs: Any
    ) -> dict[str, Any]:
        """返回完整响应（含 content 与可选 tool_calls），默认退化为纯文本。

        支持 function-calling 的 Provider 应覆写此方法；返回：
        {"content": str, "tool_calls": [{"name": str, "arguments": dict}]}
        """
        content = await self.chat(messages, **kwargs)
        return {"content": content, "tool_calls": []}

    async def embeddings(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
        raise AIServiceError(f"Provider {self.name} 不支持 embeddings")

    async def image(self, prompt: str, **kwargs: Any) -> str:
        raise AIServiceError(f"Provider {self.name} 不支持 image")

    async def speech_to_text(self, audio: bytes, **kwargs: Any) -> str:
        raise AIServiceError(f"Provider {self.name} 不支持 speech_to_text")

    async def text_to_speech(self, text: str, **kwargs: Any) -> bytes:
        raise AIServiceError(f"Provider {self.name} 不支持 text_to_speech")

    async def ocr(self, image: bytes, **kwargs: Any) -> str:
        raise AIServiceError(f"Provider {self.name} 不支持 ocr")

    def supports(self, method: str) -> bool:
        return method in self.supported_methods


class OpenAIChatProvider(AIProvider):
    name = "openai"
    supported_methods = frozenset({
        "chat",
        "embeddings",
        "image",
        "speech_to_text",
        "text_to_speech",
    })

    def __init__(
        self, *, base_url: str, api_key: str, model: str, client: httpx.AsyncClient | None = None
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self._client = client

    def _config_key(self) -> str:
        return f"{self.base_url}|{self.api_key}|{self.model}"

    async def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        client = self._client or _get_shared_client(60, self._config_key())
        response = await client.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "messages": messages, **kwargs},
        )
        response.raise_for_status()
        return _response_text(response.json(), "openai")

    async def chat_response(
        self, messages: list[dict[str, str]], **kwargs: Any
    ) -> dict[str, Any]:
        client = self._client or _get_shared_client(60, self._config_key())
        response = await client.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "messages": messages, **kwargs},
        )
        response.raise_for_status()
        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(f"OpenAI chat_response 缺少 choices: {data}")
        message = choices[0].get("message", {})
        content = message.get("content") or ""
        tool_calls: list[dict[str, Any]] = []
        for call in message.get("tool_calls") or []:
            function = call.get("function", {})
            try:
                arguments = json.loads(function.get("arguments") or "{}")
            except json.JSONDecodeError:
                arguments = {}
            tool_calls.append(
                {
                    "name": function.get("name", ""),
                    "arguments": arguments,
                }
            )
        return {"content": content, "tool_calls": tool_calls}

    async def embeddings(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
        client = self._client or _get_shared_client(60, self._config_key())
        response = await client.post(
            f"{self.base_url}/embeddings",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "input": texts, **kwargs},
        )
        response.raise_for_status()
        data = response.json()
        return [
            item.get("embedding", [])
            for item in sorted(data.get("data", []), key=lambda x: x.get("index", 0))
        ]

    async def image(self, prompt: str, **kwargs: Any) -> str:
        client = self._client or _get_shared_client(120, self._config_key())
        response = await client.post(
            f"{self.base_url}/images/generations",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "prompt": prompt, **kwargs},
        )
        response.raise_for_status()
        data = response.json()
        item = (data.get("data") or [{}])[0]
        return str(
            item.get("url")
            or item.get("b64_json")
            or ""
        )

    async def speech_to_text(self, audio: bytes, **kwargs: Any) -> str:
        client = self._client or _get_shared_client(120, self._config_key())
        response = await client.post(
            f"{self.base_url}/audio/transcriptions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            data={"model": self.model, **kwargs},
            files={"file": ("audio.bin", audio, "application/octet-stream")},
        )
        response.raise_for_status()
        return str(response.json().get("text", ""))

    async def text_to_speech(self, text: str, **kwargs: Any) -> bytes:
        client = self._client or _get_shared_client(120, self._config_key())
        response = await client.post(
            f"{self.base_url}/audio/speech",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "input": text, **kwargs},
        )
        response.raise_for_status()
        return response.content


class OllamaProvider(AIProvider):
    name = "ollama"
    supported_methods = frozenset({"chat", "embeddings"})

    def __init__(
        self, *, base_url: str, model: str, client: httpx.AsyncClient | None = None
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._client = client

    def _config_key(self) -> str:
        return f"ollama|{self.base_url}|{self.model}"

    async def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        client = self._client or _get_shared_client(60, self._config_key())
        response = await client.post(
            f"{self.base_url}/api/chat",
            json={"model": self.model, "messages": messages},
        )
        response.raise_for_status()
        return response.json().get("message", {}).get("content", "")

    async def embeddings(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
        client = self._client or _get_shared_client(120, self._config_key())
        response = await client.post(
            f"{self.base_url}/api/embed",
            json={"model": self.model, "input": texts, **kwargs},
        )
        response.raise_for_status()
        data = response.json()
        embeddings = data.get("embeddings")
        if embeddings:
            return [list(item) for item in embeddings]
        legacy = data.get("embedding")
        return [list(legacy)] if legacy else []


class AnthropicProvider(AIProvider):
    name = "anthropic"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://api.anthropic.com",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self._client = client

    def _config_key(self) -> str:
        return f"anthropic|{self.base_url}|{self.api_key}|{self.model}"

    async def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        system = "\n".join(m.get("content", "") for m in messages if m.get("role") == "system")
        user_messages = [m for m in messages if m.get("role") != "system"]
        client = self._client or _get_shared_client(60, self._config_key())
        response = await client.post(
            f"{self.base_url}/v1/messages",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": self.model,
                "system": system,
                "messages": user_messages,
            },
        )
        response.raise_for_status()
        return _response_text(response.json(), "anthropic")


class GeminiProvider(AIProvider):
    name = "gemini"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://generativelanguage.googleapis.com",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self._client = client

    def _config_key(self) -> str:
        return f"gemini|{self.base_url}|{self.api_key}|{self.model}"

    async def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        contents = []
        system_instruction = None
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if role == "system":
                system_instruction = {"parts": [{"text": content}]}
            else:
                gemini_role = "user" if role == "user" else "model"
                contents.append({"role": gemini_role, "parts": [{"text": content}]})
        client = self._client or _get_shared_client(60, self._config_key())
        body: dict[str, Any] = {"contents": contents}
        if system_instruction:
            body["systemInstruction"] = system_instruction
        response = await client.post(
            f"{self.base_url}/v1beta/models/{self.model}:generateContent",
            headers={"x-goog-api-key": self.api_key},
            json=body,
        )
        response.raise_for_status()
        return _response_text(response.json(), "gemini")


class MockAIProvider(AIProvider):
    name = "mock"
    supported_methods = frozenset({"chat"})

    async def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        return f"mock: {messages[-1].get('content', '')}"


class AIService:
    def __init__(self) -> None:
        self.providers: dict[str, AIProvider] = {}
        self.active_provider = "mock"

    def register(self, provider: AIProvider) -> None:
        self.providers[provider.name] = provider

    def set_active(self, name: str) -> None:
        if name not in self.providers:
            raise KeyError(name)
        self.active_provider = name

    def _provider(self, name: str | None) -> AIProvider:
        key = name or self.active_provider
        provider = self.providers.get(key)
        if provider is None:
            provider = self.providers.get("mock")
        if provider is None and self.providers:
            provider = next(iter(self.providers.values()))
        if provider is None:
            raise AIServiceError("未注册任何 AI Provider")
        return provider

    async def chat(
        self, messages: list[dict[str, str]], provider: str | None = None, **kwargs: Any
    ) -> str:
        return await self._provider(provider).chat(messages, **kwargs)

    async def chat_response(
        self,
        messages: list[dict[str, str]],
        provider: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return await self._provider(provider).chat_response(
            messages, **kwargs
        )

    async def embeddings(
        self, texts: list[str], provider: str | None = None, **kwargs: Any
    ) -> list[list[float]]:
        return await self._provider(provider).embeddings(texts, **kwargs)

    async def image(
        self, prompt: str, provider: str | None = None, **kwargs: Any
    ) -> str:
        return await self._provider(provider).image(prompt, **kwargs)

    async def speech_to_text(
        self, audio: bytes, provider: str | None = None, **kwargs: Any
    ) -> str:
        return await self._provider(provider).speech_to_text(audio, **kwargs)

    async def text_to_speech(
        self, text: str, provider: str | None = None, **kwargs: Any
    ) -> bytes:
        return await self._provider(provider).text_to_speech(text, **kwargs)

    async def ocr(
        self, image: bytes, provider: str | None = None, **kwargs: Any
    ) -> str:
        return await self._provider(provider).ocr(image, **kwargs)

    def matrix(self) -> dict[str, list[str]]:
        return {
            name: sorted(provider.supported_methods)
            for name, provider in sorted(self.providers.items())
        }


@dataclass
class AgentTool:
    """Agent 工具：携带描述、敏感标记与权限点。"""

    name: str
    func: Callable[..., Any]
    description: str = ""
    sensitive: bool = False
    permission: str = ""
    schema: dict[str, Any] | None = None


_REACT_CALL_RE = re.compile(
    r"工具\s*[:：]\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\(([^)]*)\)"
)


def _json_schema_for(func: Callable[..., Any]) -> dict[str, Any]:
    """由函数签名自动生成 OpenAI function-calling JSON Schema。"""
    signature = inspect.signature(func)
    properties: dict[str, Any] = {}
    required: list[str] = []
    for name, parameter in signature.parameters.items():
        if name in {"context", "self", "cls"}:
            continue
        annotation = parameter.annotation
        if annotation is inspect.Parameter.empty:
            json_type = "string"
        elif annotation is int:
            json_type = "integer"
        elif annotation is float:
            json_type = "number"
        elif annotation is bool:
            json_type = "boolean"
        elif annotation in {list, list[str]}:
            json_type = "array"
        elif annotation in {dict, dict[str, Any]}:
            json_type = "object"
        else:
            json_type = "string"
        properties[name] = {"type": json_type}
        if parameter.default is inspect.Parameter.empty:
            required.append(name)
    return {"type": "object", "properties": properties, "required": required}


def _supports_function_calling(provider: AIProvider) -> bool:
    """仅当 Provider 覆写了 chat_response（返回 tool_calls）时启用 function-calling。"""
    return type(provider).chat_response is not AIProvider.chat_response


class AgentRunner:
    """多智能体工具调用循环：function-calling 优先，非支持模型自动降级 ReAct。

    - 会话记忆：按 session_id 保留最近 N 轮，进程内存储。
    - 工具 schema：默认由函数签名自动生成，注册时可手动覆盖。
    - 敏感工具：注册时标记 sensitive + permission，运行时经 permission_check 授权。
    - 运行日志：每轮工具调用/结果/耗时，供 Web「会话运行日志」展示。
    """

    _MAX_SESSIONS = 200
    _MAX_MEMORY_PER_SESSION = 20

    def __init__(self, ai: AIService, *, max_memory_turns: int = 10) -> None:
        self.ai = ai
        self.tools: dict[str, AgentTool] = {}
        self.memories: dict[str, deque[dict[str, str]]] = {}
        self.run_logs: deque[dict[str, Any]] = deque(maxlen=200)
        self.max_memory_turns = max(2, int(max_memory_turns))

    def register_tool(
        self,
        name: str,
        func: Callable[..., Any],
        *,
        description: str = "",
        sensitive: bool = False,
        permission: str = "",
        schema: dict[str, Any] | None = None,
    ) -> AgentTool:
        tool = AgentTool(
            name=name,
            func=func,
            description=description,
            sensitive=sensitive,
            permission=permission,
            schema=schema,
        )
        self.tools[name] = tool
        return tool

    def unregister_tool(self, name: str) -> bool:
        return self.tools.pop(name, None) is not None

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "sensitive": tool.sensitive,
                "permission": tool.permission,
            }
            for tool in sorted(self.tools.values(), key=lambda item: item.name)
        ]

    def tool_schemas(self, names: list[str] | None = None) -> list[dict[str, Any]]:
        schemas: list[dict[str, Any]] = []
        for name, tool in sorted(self.tools.items()):
            if names is not None and name not in names:
                continue
            schema = tool.schema or _json_schema_for(tool.func)
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": schema,
                    },
                }
            )
        return schemas

    def _memory(self, session_id: str) -> deque[dict[str, str]]:
        if session_id not in self.memories:
            if len(self.memories) >= self._MAX_SESSIONS:
                self.memories.pop(next(iter(self.memories)))
            self.memories[session_id] = deque(maxlen=self._MAX_MEMORY_PER_SESSION)
        return self.memories[session_id]

    async def _authorized(
        self, tool: AgentTool, permission_check: Callable[[str], bool] | None
    ) -> bool:
        if not tool.sensitive:
            return True
        if permission_check is None:
            return False
        return bool(permission_check(tool.permission))

    async def _execute_tool(
        self,
        tool: AgentTool,
        arguments: dict[str, Any],
        tool_timeout: float,
    ) -> tuple[str, float]:
        started = time.monotonic()
        if inspect.iscoroutinefunction(tool.func):
            result = await asyncio.wait_for(
                tool.func(**arguments), timeout=tool_timeout
            )
        else:
            result = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(
                    None, lambda: tool.func(**arguments)
                ),
                timeout=tool_timeout,
            )
        elapsed = round((time.monotonic() - started) * 1000, 1)
        if result is None:
            return "（无返回）", elapsed
        if not isinstance(result, str):
            try:
                result = json.dumps(result, ensure_ascii=False, default=str)
            except (TypeError, ValueError):
                result = str(result)
        return str(result), elapsed

    @staticmethod
    def _parse_react(text: str) -> tuple[str | None, dict[str, Any] | None]:
        """解析 ReAct 文本中的「工具: name(args)」调用。"""
        match = _REACT_CALL_RE.search(text)
        if match is None:
            return None, None
        name, raw_args = match.group(1), match.group(2).strip()
        arguments: dict[str, Any] = {}
        if raw_args:
            try:
                parsed = json.loads(raw_args)
                arguments = parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                for token in raw_args.split(","):
                    if "=" not in token:
                        continue
                    key, _, value = token.partition("=")
                    arguments[key.strip()] = value.strip().strip("'\"")
        return name, arguments

    async def run(
        self,
        prompt: str,
        *,
        session_id: str = "",
        tools: list[str] | None = None,
        max_rounds: int = 5,
        tool_timeout: float = 10.0,
        provider: str | None = None,
        permission_check: Callable[[str], bool] | None = None,
        system_prompt: str = "",
    ) -> str:
        max_rounds = max(1, int(max_rounds))
        tool_timeout = max(1.0, float(tool_timeout))
        memory = self._memory(session_id)
        memory.append({"role": "user", "content": prompt})

        tool_names = tools or list(self.tools)
        available = {
            name: tool
            for name, tool in self.tools.items()
            if name in tool_names
        }
        react_mode = not _supports_function_calling(
            self.ai._provider(provider)
        ) or not available
        base_system = (
            system_prompt
            or "你是一个 OFbot 2 助手，可以使用工具完成用户请求。"
        )
        if react_mode and available:
            base_system += (
                "\n当需要调用工具时，严格输出一行："
                "工具: 工具名(参数JSON)\n"
                "例如：工具: send_group({\"group_id\": \"1\", \"message\": \"hi\"})"
            )
        messages: list[dict[str, str]] = [
            {"role": "system", "content": base_system},
            *list(memory),
        ]

        steps: list[dict[str, Any]] = []
        final = ""
        started = time.monotonic()
        try:
            for _ in range(max_rounds):
                if react_mode:
                    response = await self.ai.chat_response(
                        messages, provider=provider
                    )
                    content = response.get("content") or ""
                    name, arguments = self._parse_react(content)
                    calls: list[dict[str, Any]] = (
                        [{"name": name, "arguments": arguments}]
                        if name is not None
                        else []
                    )
                else:
                    response = await self.ai.chat_response(
                        messages,
                        provider=provider,
                        tools=self.tool_schemas(list(available)),
                        tool_choice="auto",
                    )
                    content = response.get("content") or ""
                    calls = response.get("tool_calls") or []
                if not calls:
                    final = content.strip()
                    break
                if content.strip():
                    messages.append(
                        {"role": "assistant", "content": content}
                    )
                for call in calls:
                    tool = available.get(call.get("name", ""))
                    if tool is None:
                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    f"工具 {call.get('name')} 不存在，"
                                    "请使用可用工具。"
                                ),
                            }
                        )
                        steps.append(
                            {
                                "tool": call.get("name"),
                                "input": call.get("arguments"),
                                "output": "工具不存在",
                                "elapsed_ms": 0,
                            }
                        )
                        continue
                    if not await self._authorized(
                        tool, permission_check
                    ):
                        steps.append(
                            {
                                "tool": tool.name,
                                "input": call.get("arguments"),
                                "output": "无权限",
                                "elapsed_ms": 0,
                            }
                        )
                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    f"工具 {tool.name} 需要授权，"
                                    "请告知用户联系管理员。"
                                ),
                            }
                        )
                        continue
                    try:
                        output, elapsed = await self._execute_tool(
                            tool, call.get("arguments") or {}, tool_timeout
                        )
                        step_output = output
                    except Exception as exc:
                        elapsed = 0.0
                        step_output = f"工具执行失败：{exc}"
                    steps.append(
                        {
                            "tool": tool.name,
                            "input": call.get("arguments"),
                            "output": step_output,
                            "elapsed_ms": elapsed,
                        }
                    )
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                f"工具 {tool.name} 返回：{step_output}"
                            ),
                        }
                    )
            else:
                final = "已达到最大工具调用轮次，请简化请求或检查工具。"
        except Exception as exc:
            logger.exception("agent run failed")
            final = f"AI 调用失败：{exc}"
        finally:
            memory.append({"role": "assistant", "content": final})
            self.run_logs.append(
                {
                    "session_id": session_id,
                    "prompt": prompt,
                    "rounds": len(steps),
                    "steps": steps,
                    "final": final,
                    "elapsed_ms": round(
                        (time.monotonic() - started) * 1000, 1
                    ),
                    "timestamp": time.time(),
                }
            )
        return final

    def get_logs(
        self, session_id: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        logs = list(self.run_logs)
        if session_id is not None:
            logs = [
                item for item in logs if item["session_id"] == session_id
            ]
        return list(reversed(logs))[: max(1, int(limit))]


def register_ai_capability() -> Capability:
    return Capability(
        name="ai",
        description="统一 AI Provider 与多智能体工具",
        methods=["chat", "embeddings", "image", "speech_to_text", "text_to_speech", "ocr", "agent"],
    )
