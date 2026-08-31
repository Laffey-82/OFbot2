"""order_ledger 指令层测试：通过真实 SQLite + 假事件直接调用处理器。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.messages import Message
from app.core.permissions import Principal
from app.core.plugin import PluginContext
from app.db.base import get_engine, init_db, reset_db_engine, session_factory
from plugins.order_ledger import handlers, services


class FakePermissions:
    def __init__(self, role: str = "user") -> None:
        self.role = role

    def get_principal(self, user_id: str) -> Principal:
        return Principal(user_id, self.role, set(), set())


class FakeEvent:
    def __init__(
        self,
        user_id: str = "100",
        group_id: str = "200",
        nickname: str = "测试昵称",
    ) -> None:
        self.user_id = user_id
        self.group_id = group_id
        self.sender = SimpleNamespace(nickname=nickname, card="")
        self.replies: list = []

    async def reply(self, content) -> None:
        self.replies.append(str(content))


@pytest.fixture
async def env(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 'test_handlers.db'}"
    get_engine(url)
    await init_db(url)
    permissions = FakePermissions()
    fake_ctx = PluginContext(
        name="order_ledger",
        config={},
        bus=None,
        commands=None,
        db=session_factory,
        scheduler=None,
        cache=None,
        bot=None,
        permissions=permissions,
        services={},
        subscriptions=None,
    )
    services.init(fake_ctx)
    handlers.init(fake_ctx)
    yield SimpleNamespace(
        ctx=fake_ctx,
        permissions=permissions,
        db_url=url,
    )
    await reset_db_engine()


async def _full_flow(event: FakeEvent) -> None:
    await handlers.record_order(
        event, Message("白系理论 1 0 1 100 官机打"), SimpleNamespace(params=None)
    )
    assert "订单录入成功" in event.replies[-1]
    assert "白系理论" in event.replies[-1]
    assert "官机打" in event.replies[-1]

    await handlers.query_orders(event, Message("未接单"), SimpleNamespace(params=None))
    assert "订单列表" in event.replies[-1]

    await handlers.take_order(
        event, Message("1"), SimpleNamespace(params={"seq": 1})
    )
    assert "接单成功" in event.replies[-1]

    await handlers.complete_order(
        event, Message("1"), SimpleNamespace(params={"seq": 1})
    )
    assert "订单已完成" in event.replies[-1]


async def test_full_order_flow(env):
    event = FakeEvent()
    await _full_flow(event)
    # 发单人视角统计
    await handlers.stats(event, Message("全部"), SimpleNamespace(params=None))
    assert "总营收" in event.replies[-1]
    # 排行
    await handlers.rank(event, Message("全部 全部"), SimpleNamespace(params=None))
    assert "排行" in event.replies[-1]
    # 账目
    await handlers.account(event, Message(""), SimpleNamespace(params=None))
    assert "个人账目中心" in event.replies[-1]
    # 我的订单
    await handlers.my_orders(event, Message(""), SimpleNamespace(params=None))
    assert "我的订单" in event.replies[-1]


async def test_permission_denied_for_admin_commands(env):
    event = FakeEvent()
    await handlers.delete_order(
        event, Message("1"), SimpleNamespace(params={"seq": 1})
    )
    assert "权限不足" in event.replies[-1]
    await handlers.run_commission(
        event, Message("昨日"), SimpleNamespace(params=None)
    )
    assert "权限不足" in event.replies[-1]


async def test_admin_commands(env):
    event = FakeEvent()
    await _full_flow(event)
    env.permissions.role = "admin"
    await handlers.highlight_order(
        event, Message("1"), SimpleNamespace(params={"seq": 1})
    )
    assert "已标记急单" in event.replies[-1]
    await handlers.run_commission(
        event, Message("昨日"), SimpleNamespace(params=None)
    )
    assert "分账操作已执行完成" in event.replies[-1]
    await handlers.commission_history(
        event, Message("昨日"), SimpleNamespace(params=None)
    )
    assert "分账历史" in event.replies[-1]


async def test_remark_and_price(env):
    event = FakeEvent()
    await _full_flow(event)
    await handlers.remark_order(
        event, Message("1 加急"), SimpleNamespace(params={"seq": 1, "content": "加急"})
    )
    assert "备注已更新" in event.replies[-1]
    await handlers.change_price(
        event, Message("1 120"), SimpleNamespace(params={"seq": 1, "price": 120.0})
    )
    assert "价格已更新" in event.replies[-1]


async def test_plain_confirm_listener(env):
    event = FakeEvent()
    await handlers.record_order(
        event, Message("白系理论 1 0 1 100"), SimpleNamespace(params=None)
    )
    await handlers.take_order(
        event, Message("1"), SimpleNamespace(params={"seq": 1})
    )
    event.replies.clear()

    sent: list = []

    async def fake_send_group(group_id: str, message) -> bool:
        sent.append((group_id, str(message)))
        return True

    env.ctx.send_group = fake_send_group
    await handlers.on_plain_confirm(
        SimpleNamespace(
            message="确认 1",
            group_id="200",
            user_id="100",
            raw_event={
                "sender": {"nickname": "测试昵称", "card": ""}
            },
        )
    )
    assert sent and "订单已完成" in sent[0][1]


async def test_status_cmd(env):
    event = FakeEvent()
    await _full_flow(event)
    await handlers.status_cmd(event, Message(""), SimpleNamespace(params=None))
    assert "订单统计" in event.replies[-1]
