from __future__ import annotations

import pytest

from app.services.ai import (
    AgentRunner,
    AIService,
    MockAIProvider,
)


class ToolCallingMockProvider(MockAIProvider):
    """测试用：按调用次数依次返回 tool_calls 序列，最后给出文本回复。"""

    name = "toolmock"

    def __init__(self, script: list[dict]) -> None:
        self.script = script
        self.calls: list[dict] = []

    async def chat_response(self, messages, **kwargs):
        self.calls.append(kwargs)
        if not self.script:
            return {"content": "完成", "tool_calls": []}
        return self.script.pop(0)


class ReActTextProvider(MockAIProvider):
    """仅实现 chat（不覆写 chat_response），用于验证 ReAct 降级。"""

    name = "reactmock"

    def __init__(self, script: list[str]) -> None:
        self.script = script

    async def chat(self, messages, **kwargs):
        if not self.script:
            return "完成"
        return self.script.pop(0)


def _service(provider=None) -> AIService:
    service = AIService()
    service.register(provider or MockAIProvider())
    service.set_active(provider.name if provider else "mock")
    return service


@pytest.mark.asyncio
async def test_agent_function_calling_loop() -> None:
    provider = ToolCallingMockProvider(
        [
            {
                "content": "",
                "tool_calls": [
                    {
                        "name": "add",
                        "arguments": {"a": 1, "b": 2},
                    }
                ],
            },
            {"content": "结果是 3", "tool_calls": []},
        ]
    )
    runner = AgentRunner(_service(provider))
    runner.register_tool(
        "add",
        lambda a, b: a + b,
        description="加法",
    )
    result = await runner.run("1+2 等于多少？", max_rounds=5)
    assert result == "结果是 3"
    assert len(runner.get_logs()) == 1
    log = runner.get_logs()[0]
    assert log["steps"][0]["tool"] == "add"
    assert log["steps"][0]["output"] == "3"
    assert log["rounds"] == 1


@pytest.mark.asyncio
async def test_agent_react_fallback() -> None:
    provider = ReActTextProvider(
        [
            "我需要查询：工具: double(x=4)",
            "答案是 8",
        ]
    )
    service = _service(provider)
    runner = AgentRunner(service)
    runner.register_tool("double", lambda x: int(x) * 2)
    result = await runner.run("4 的两倍？", max_rounds=5)
    assert result == "答案是 8"
    assert runner.get_logs()[0]["steps"][0]["tool"] == "double"


@pytest.mark.asyncio
async def test_agent_max_rounds() -> None:
    provider = ToolCallingMockProvider(
        [
            {
                "content": "",
                "tool_calls": [
                    {"name": "echo", "arguments": {"v": "x"}}
                ],
            }
        ]
        * 10
    )
    runner = AgentRunner(_service(provider))
    runner.register_tool("echo", lambda v: v)
    result = await runner.run("循环", max_rounds=2)
    assert "最大工具调用轮次" in result


@pytest.mark.asyncio
async def test_agent_sensitive_tool_permission() -> None:
    provider = ToolCallingMockProvider(
        [
            {
                "content": "",
                "tool_calls": [
                    {"name": "send", "arguments": {"m": "hi"}}
                ],
            },
            {"content": "已处理", "tool_calls": []},
        ]
    )
    runner = AgentRunner(_service(provider))
    runner.register_tool(
        "send",
        lambda m: m,
        sensitive=True,
        permission="bot.message",
    )
    result = await runner.run(
        "发消息", permission_check=lambda perm: False
    )
    assert result == "已处理"
    assert runner.get_logs()[0]["steps"][0]["output"] == "无权限"


@pytest.mark.asyncio
async def test_agent_memory_and_timeout() -> None:
    async def slow(_v: str) -> str:
        import asyncio

        await asyncio.sleep(1)
        return "done"

    provider = ToolCallingMockProvider(
        [
            {
                "content": "",
                "tool_calls": [{"name": "slow", "arguments": {"v": "x"}}],
            },
            {"content": "结束", "tool_calls": []},
        ]
    )
    runner = AgentRunner(_service(provider))
    runner.register_tool("slow", slow)
    result = await runner.run(
        "测试超时", tool_timeout=0.1, max_rounds=2
    )
    assert result == "结束"
    assert "工具执行失败" in runner.get_logs()[0]["steps"][0]["output"]
    assert len(runner.memories.get("", [])) == 2  # user + assistant
