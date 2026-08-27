from __future__ import annotations

import httpx
import pytest

from app.services.ai import (
    AIService,
    AIServiceError,
    AnthropicProvider,
    MockAIProvider,
    OllamaProvider,
    OpenAIChatProvider,
)


@pytest.mark.asyncio
async def test_openai_compatible_multimodal() -> None:
    """OpenAI 兼容 Provider 的 embeddings/image/stt/tts 真实接线。"""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/embeddings"):
            return httpx.Response(
                200, json={"data": [{"index": 0, "embedding": [1.0, 2.0]}]}
            )
        if request.url.path.endswith("/images/generations"):
            return httpx.Response(200, json={"data": [{"url": "https://x/a.png"}]})
        if request.url.path.endswith("/audio/transcriptions"):
            return httpx.Response(200, json={"text": "你好"})
        if request.url.path.endswith("/audio/speech"):
            return httpx.Response(200, content=b"mp3data")
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAIChatProvider(
        base_url="https://api.openai.com/v1",
        api_key="k",
        model="m",
        client=client,
    )
    assert await provider.embeddings(["hi"]) == [[1.0, 2.0]]
    assert await provider.image("cat") == "https://x/a.png"
    assert await provider.speech_to_text(b"audio") == "你好"
    assert await provider.text_to_speech("hi") == b"mp3data"
    assert len(seen) == 4
    await client.aclose()


@pytest.mark.asyncio
async def test_unsupported_provider_raises_clear_error() -> None:
    provider = AnthropicProvider(api_key="k", model="m")
    with pytest.raises(AIServiceError, match="embeddings"):
        await provider.embeddings(["x"])
    with pytest.raises(AIServiceError, match="ocr"):
        await provider.ocr(b"x")


@pytest.mark.asyncio
async def test_mock_provider_chat_only() -> None:
    mock = MockAIProvider()
    assert (
        await mock.chat([{"role": "user", "content": "hi"}])
    ) == "mock: hi"
    with pytest.raises(AIServiceError):
        await mock.embeddings(["x"])
    with pytest.raises(AIServiceError):
        await mock.image("cat")


@pytest.mark.asyncio
async def test_ollama_embeddings() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/embed"
        return httpx.Response(200, json={"embeddings": [[0.5, 0.6]]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OllamaProvider(
        base_url="http://127.0.0.1:11434", model="m", client=client
    )
    assert await provider.embeddings(["hi"]) == [[0.5, 0.6]]
    await client.aclose()


def test_ai_support_matrix() -> None:
    service = AIService()
    service.register(
        OpenAIChatProvider(base_url="x", api_key="k", model="m")
    )
    service.register(MockAIProvider())
    matrix = service.matrix()
    assert "embeddings" in matrix["openai"]
    assert matrix["mock"] == ["chat"]
