"""AI 服务与 system 插件修复验证测试。"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.core.scopes import ScopePolicyService
from app.services.ai import (
    AgentRunner,
    AIService,
    GeminiProvider,
    MockAIProvider,
    OpenAIChatProvider,
    _response_text,
)

# ── Defect 1: 功能开关持久化 ────────────────────────────────────────────────


def test_feature_toggle_persists_via_settings_reference(tmp_path):
    """set_feature 后 persist() 应把变更写入磁盘。"""
    config_path = tmp_path / "config.yaml"
    from app.core.config import load_settings, save_settings

    settings = load_settings(config_path)
    save_settings(settings)
    policy = ScopePolicyService(settings)

    scope = "group:123456"
    policy.set_feature(scope, "dice.roll", False)
    assert policy.feature_value(scope, "dice.roll") is False

    policy.persist()

    reloaded = load_settings(config_path)
    assert reloaded.runtime.scopes[scope].features.get("dice.roll") is False


def test_feature_toggle_persist_preserves_existing(tmp_path):
    """持久化不应丢失已有的 scope 配置。"""
    config_path = tmp_path / "config.yaml"
    from app.core.config import load_settings, save_settings

    settings = load_settings(config_path)
    save_settings(settings)
    policy = ScopePolicyService(settings)

    scope = "group:999"
    policy.set_feature(scope, "music.play", True)
    policy.set_feature(scope, "game.start", False)
    policy.persist()

    reloaded = load_settings(config_path)
    assert reloaded.runtime.scopes[scope].features.get("music.play") is True
    assert reloaded.runtime.scopes[scope].features.get("game.start") is False


def test_persist_noop_without_settings():
    """_settings 为 None 时 persist 不应抛异常。"""
    policy = ScopePolicyService(None)
    policy.persist()


# ── Defect 4: choices/content 空响应抛 RuntimeError ─────────────────────────


def test_openai_empty_choices_raises():
    with pytest.raises(RuntimeError, match="choices"):
        _response_text({}, "openai")


def test_openai_empty_content_raises():
    data = {"choices": [{"message": {"content": ""}}]}
    with pytest.raises(RuntimeError, match="content 为空"):
        _response_text(data, "openai")


def test_gemini_empty_candidates_raises():
    with pytest.raises(RuntimeError, match="candidates"):
        _response_text({}, "gemini")


def test_gemini_empty_text_raises():
    data = {"candidates": [{"content": {"parts": []}}]}
    with pytest.raises(RuntimeError, match="text 为空"):
        _response_text(data, "gemini")


def test_anthropic_empty_content_raises():
    with pytest.raises(RuntimeError, match="content"):
        _response_text({}, "anthropic")


def test_openai_valid_response():
    data = {"choices": [{"message": {"content": "ok"}}]}
    assert _response_text(data, "openai") == "ok"


def test_gemini_valid_response():
    data = {"candidates": [{"content": {"parts": [{"text": "hi"}]}}]}
    assert _response_text(data, "gemini") == "hi"


# ── Defect 5: Gemini key 改用 header + system role 修复 ────────────────────


@pytest.mark.asyncio
async def test_gemini_uses_header_not_url_param():
    """Gemini api_key 应通过 x-goog-api-key header 而非 URL 查询参数传递。"""
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = GeminiProvider(api_key="test-key", model="gemini-pro", client=client)
    result = await provider.chat([{"role": "user", "content": "hi"}])
    assert result == "ok"
    assert captured
    req = captured[0]
    assert "x-goog-api-key" in req.headers
    assert req.headers["x-goog-api-key"] == "test-key"
    assert "key" not in str(req.url)
    await client.aclose()


@pytest.mark.asyncio
async def test_gemini_system_role_mapped_to_system_instruction():
    """system 消息应映射到 systemInstruction 而非 contents 中的 model role。"""
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = GeminiProvider(api_key="k", model="m", client=client)
    await provider.chat([
        {"role": "system", "content": "你是助手"},
        {"role": "user", "content": "你好"},
    ])
    body = json.loads(captured[0].content)
    assert "systemInstruction" in body
    assert body["systemInstruction"]["parts"][0]["text"] == "你是助手"
    for item in body["contents"]:
        assert item["role"] != "model" or item["parts"][0]["text"] != "你是助手"
    await client.aclose()


# ── Defect 6: AgentRunner 记忆限量 ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_agent_memory_per_session_capped():
    """单个 session 记忆不超过 _MAX_MEMORY_PER_SESSION 条。"""
    provider = MockAIProvider()
    service = AIService()
    service.register(provider)
    service.set_active("mock")
    runner = AgentRunner(service)

    mem = runner._memory("s1")
    for i in range(25):
        mem.append({"role": "user", "content": str(i)})
    assert len(mem) <= AgentRunner._MAX_MEMORY_PER_SESSION


@pytest.mark.asyncio
async def test_agent_session_count_capped():
    """总 session 数不超过 _MAX_SESSIONS。"""
    provider = MockAIProvider()
    service = AIService()
    service.register(provider)
    service.set_active("mock")
    runner = AgentRunner(service)

    for i in range(210):
        runner._memory(f"session_{i}")

    assert len(runner.memories) <= AgentRunner._MAX_SESSIONS


# ── Defect 6: 同步工具超时 ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sync_tool_runs_in_executor():
    """同步工具应通过 run_in_executor 执行，不阻塞事件循环。"""

    def blocking_tool():
        return "done"

    provider = MockAIProvider()
    service = AIService()
    service.register(provider)
    service.set_active("mock")
    runner = AgentRunner(service)
    runner.register_tool("blocking", blocking_tool)

    output, _elapsed = await runner._execute_tool(
        runner.tools["blocking"], {}, 5.0
    )
    assert output == "done"


@pytest.mark.asyncio
async def test_sync_tool_timeout():
    """同步工具超过 tool_timeout 应抛 TimeoutError。"""
    import time

    def slow_tool():
        time.sleep(10)
        return "late"

    provider = MockAIProvider()
    service = AIService()
    service.register(provider)
    service.set_active("mock")
    runner = AgentRunner(service)
    runner.register_tool("slow", slow_tool)

    with pytest.raises(asyncio.TimeoutError):
        await runner._execute_tool(runner.tools["slow"], {}, 0.1)


# ── Defect 2: interval=0 报错 ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_task_add_interval_zero_seconds_rejected():
    """interval 为 0 或负数应被拒绝。"""
    from pathlib import Path

    from app.adapters.base import BotClient
    from app.core.cache import TTLCache
    from app.core.commands import CommandRegistry
    from app.core.messages import GroupMessageEvent, Message, Sender
    from app.core.permissions import PermissionManager, permission_manager
    from app.core.plugin import PluginManager
    from app.core.scheduler import SchedulerService
    from app.core.security import SecurityPolicy
    from app.core.subscriptions import EventSubscriptionRegistry
    from app.core.whitelist import GroupWhitelistService

    commands = CommandRegistry()
    commands.set_command_start(["/"])
    commands.set_security(SecurityPolicy())
    permissions = PermissionManager()
    permission_manager.upsert_principal("100", role="superadmin", scopes={"*"})
    subscriptions = EventSubscriptionRegistry()
    scheduler = SchedulerService()
    manager = PluginManager(
        Path(__file__).resolve().parents[1] / "plugins",
        commands=commands,
        db=None,
        scheduler=scheduler,
        cache=TTLCache(),
        bot=BotClient(),
        permissions=permissions,
        services={"whitelist": GroupWhitelistService([])},
        subscriptions=subscriptions,
    )
    manager.load_enabled({"system": True}, {"system": {"groups": []}})

    event = GroupMessageEvent(
        bot_id="test",
        self_id="10",
        raw_event={},
        message_id="1",
        user_id="100",
        sender=Sender("100", "admin"),
        message=Message("/task add interval test 100 0 hello"),
        group_id="100",
    )
    replies: list[str] = []

    async def reply(content):
        replies.append(
            content.extract_plain_text()
            if hasattr(content, "extract_plain_text")
            else str(content)
        )

    event.reply = reply
    await commands.handle_message(event)
    assert replies and ("正整数" in replies[0] or "数字" in replies[0])

    await manager.unload_plugin("system")
    scheduler.shutdown()


# ── Defect 3: 成功任务清除 last_error ──────────────────────────────────────


def test_success_task_clears_last_error():
    """execute_task 成功路径应清除 params 中的 last_error。"""
    params = {"group_id": "1", "message": "hi", "last_error": "旧错误"}
    cleaned = {k: v for k, v in params.items() if k != "last_error"}
    assert "last_error" not in cleaned
    assert cleaned["group_id"] == "1"


# ── Defect 4: 共享 httpx client ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_shared_client_reused_for_same_config():
    """相同 config_key 应复用同一 AsyncClient。"""
    import app.services.ai as ai_mod

    old_client = ai_mod._shared_client
    old_key = ai_mod._shared_client_config

    ai_mod._shared_client = None
    ai_mod._shared_client_config = ""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAIChatProvider(
        base_url="https://api.test.com/v1",
        api_key="k",
        model="m",
        client=client,
    )
    result1 = await provider.chat([{"role": "user", "content": "a"}])
    result2 = await provider.chat([{"role": "user", "content": "b"}])
    assert result1 == "ok"
    assert result2 == "ok"
    await client.aclose()

    ai_mod._shared_client = old_client
    ai_mod._shared_client_config = old_key
