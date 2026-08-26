from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx

from app.core.capabilities import Capability
from app.core.logger import get_logger

logger = get_logger(__name__)


class AIProvider:
    name = "base"

    async def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        raise NotImplementedError

    async def embeddings(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
        raise NotImplementedError

    async def image(self, prompt: str, **kwargs: Any) -> str:
        raise NotImplementedError

    async def speech_to_text(self, audio: bytes, **kwargs: Any) -> str:
        raise NotImplementedError

    async def text_to_speech(self, text: str, **kwargs: Any) -> bytes:
        raise NotImplementedError

    async def ocr(self, image: bytes, **kwargs: Any) -> str:
        raise NotImplementedError


class OpenAIChatProvider(AIProvider):
    name = "openai"

    def __init__(
        self, *, base_url: str, api_key: str, model: str, client: httpx.AsyncClient | None = None
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self._client = client

    async def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        client = self._client or httpx.AsyncClient(timeout=60)
        try:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": messages,
                    **kwargs,
                },
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        finally:
            if self._client is None:
                await client.aclose()


class OllamaProvider(AIProvider):
    name = "ollama"

    def __init__(
        self, *, base_url: str, model: str, client: httpx.AsyncClient | None = None
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._client = client

    async def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        client = self._client or httpx.AsyncClient(timeout=60)
        try:
            response = await client.post(
                f"{self.base_url}/api/chat",
                json={"model": self.model, "messages": messages},
            )
            response.raise_for_status()
            return response.json().get("message", {}).get("content", "")
        finally:
            if self._client is None:
                await client.aclose()


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

    async def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        system = "\n".join(m.get("content", "") for m in messages if m.get("role") == "system")
        user_messages = [m for m in messages if m.get("role") != "system"]
        client = self._client or httpx.AsyncClient(timeout=60)
        try:
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
            data = response.json()
            return "".join(block.get("text", "") for block in data.get("content", []))
        finally:
            if self._client is None:
                await client.aclose()


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

    async def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        contents = [
            {"role": "user" if m.get("role") == "user" else "model", "parts": [{"text": m.get("content", "")}]}
            for m in messages
        ]
        client = self._client or httpx.AsyncClient(timeout=60)
        try:
            response = await client.post(
                f"{self.base_url}/v1beta/models/{self.model}:generateContent",
                params={"key": self.api_key},
                json={"contents": contents},
            )
            response.raise_for_status()
            data = response.json()
            try:
                return data["candidates"][0]["content"]["parts"][0]["text"]
            except (KeyError, IndexError):
                return ""
        finally:
            if self._client is None:
                await client.aclose()


class MockAIProvider(AIProvider):
    name = "mock"

    async def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        return f"mock: {messages[-1].get('content', '')}"

    async def embeddings(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
        return [[0.1] * 8 for _ in texts]

    async def image(self, prompt: str, **kwargs: Any) -> str:
        return f"mock-image:{prompt}"

    async def speech_to_text(self, audio: bytes, **kwargs: Any) -> str:
        return "mock speech text"

    async def text_to_speech(self, text: str, **kwargs: Any) -> bytes:
        return b"mock audio"

    async def ocr(self, image: bytes, **kwargs: Any) -> str:
        return "mock ocr text"


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
        return self.providers.get(key, self.providers["mock"])

    async def chat(
        self, messages: list[dict[str, str]], provider: str | None = None, **kwargs: Any
    ) -> str:
        return await self._provider(provider).chat(messages, **kwargs)

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


class AgentRunner:
    def __init__(self, ai: AIService) -> None:
        self.ai = ai
        self.tools: dict[str, Callable[..., Any]] = {}

    def register_tool(self, name: str, func: Callable[..., Any]) -> None:
        self.tools[name] = func

    async def run(self, prompt: str, tools: list[str] | None = None) -> str:
        messages = [{"role": "system", "content": "你是一个助手，可以使用工具。"}]
        messages.append({"role": "user", "content": prompt})
        result = await self.ai.chat(messages)
        return result


def register_ai_capability() -> Capability:
    return Capability(
        name="ai",
        description="统一 AI Provider 与多智能体工具",
        methods=["chat", "embeddings", "image", "speech_to_text", "text_to_speech", "ocr", "agent"],
    )
