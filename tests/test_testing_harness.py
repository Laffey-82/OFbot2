"""FakeBotHarness 冒烟：子进程启动真实机器人并验证 /ping。"""

from __future__ import annotations

import pytest

from app.testing import FakeBotHarness


@pytest.mark.asyncio
async def test_harness_ping() -> None:
    async with FakeBotHarness(plugins={"system": True, "template": True}) as bot:
        reply = await bot.send_group("200", "/ping")
        assert "pong" in reply
