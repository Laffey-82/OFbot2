"""order_ledger 服务层测试：时间、分账、订单仓储、历史、统计/排行/账目、导出。"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.core.plugin import PluginContext
from app.db.base import get_engine, init_db, reset_db_engine, session_factory
from plugins.order_ledger import models, services  # noqa: F401


@pytest.fixture
async def db(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 'test_services.db'}"
    get_engine(url)
    await init_db(url)
    fake_ctx = PluginContext(
        name="order_ledger",
        config={},
        bus=None,
        commands=None,
        db=session_factory,
        scheduler=None,
        cache=None,
        bot=None,
        permissions=object(),
        services={},
        subscriptions=None,
    )
    services.init(fake_ctx)
    yield fake_ctx
    await reset_db_engine()


async def _make_order(group_id: str = "200", seq: int | None = None) -> dict:
    order = await services.create_order(
        group_id,
        order_info="测试单",
        control_score="1",
        control_dx="0",
        need_score_img="1",
        price=100.0,
        creator_qq="100",
        creator_nick="发单人",
        remark="",
    )
    return order.as_dict()


def test_parse_time_param():
    start, end, desc = services.parse_time_param("昨日")
    assert start == end == services.yesterday()
    assert desc == "昨日"
    start, end, desc = services.parse_time_param("20260801")
    assert (start, end, desc) == ("2026-08-01", "2026-08-01", "2026-08-01")
    start, end, desc = services.parse_time_param("20260801 20260803")
    assert (start, end) == ("2026-08-01", "2026-08-03")
    start, end, desc = services.parse_time_param("全部")
    assert start == end == ""


def test_week_range():
    start, end = services.week_range(
        5, datetime(2026, 8, 29, 12, 0, tzinfo=services.BJ_TZ)
    )
    # 2026-08-29 是周六，本周起始即当天
    assert start == "2026-08-29"
    assert end == "2026-08-29"
    start, end = services.week_range(
        5, datetime(2026, 9, 1, 12, 0, tzinfo=services.BJ_TZ)
    )
    assert start == "2026-08-29"
    assert end == "2026-09-01"


def test_commission():
    commission = services.Commission()
    assert commission.validate_ratio()
    fees = commission.calculate(100.0)
    assert abs(sum(fees.values()) - 100.0) < 0.01
    assert fees["打手"] == pytest.approx(69.0)
    assert fees["接单人"] == pytest.approx(26.0)


async def test_order_crud(db):
    order = await _make_order()
    assert order["status"] == "未接单"
    assert order["fixed_seq"] == 1

    second = await _make_order()
    assert second["fixed_seq"] == 2

    fetched = await services.get_order("200", 1)
    assert fetched is not None and fetched.order_info == "测试单"

    ok, _message, taken = await services.take_order("200", 1, "200", "打手甲")
    assert ok and taken["status"] == "已接单"
    # 重复接单应失败
    ok2, _, _ = await services.take_order("200", 1, "300", "打手乙")
    assert not ok2

    updated = await services.update_order(
        "200",
        1,
        status="已完成",
        complete_time=services.now_str(),
        confirmer_qq="100",
        confirmer_nick="发单人",
    )
    assert updated is not None and updated.status == "已完成"

    rows = await services.list_orders("200", statuses=["已完成"])
    assert len(rows) == 1
    rows_all = await services.list_orders("200")
    assert len(rows_all) == 2

    assert await services.delete_order("200", 2) is True
    assert await services.get_order("200", 2) is None


async def test_delete_orders_by_ids(db):
    await _make_order()
    await _make_order()
    ids = [o["id"] for o in await services.list_orders("200")]
    assert len(ids) == 2
    assert await services.delete_orders_by_ids(ids) == 2
    assert await services.list_orders("200") == []


async def test_check_overdue(db):
    order = await services.create_order(
        "200",
        order_info="旧单",
        control_score="1",
        control_dx="1",
        need_score_img="1",
        price=50.0,
        creator_qq="100",
        creator_nick="发单人",
    )
    old_time = "2026-01-01 10:00:00"
    await services.update_order(
        "200", order.fixed_seq, create_time=old_time
    )
    remind = await services.check_overdue("200")
    assert [o["fixed_seq"] for o in remind] == [order.fixed_seq]

    # 已接单超时还原
    order2 = await services.create_order(
        "200",
        order_info="超时接单",
        control_score="1",
        control_dx="1",
        need_score_img="1",
        price=50.0,
        creator_qq="100",
        creator_nick="发单人",
    )
    await services.take_order("200", order2.fixed_seq, "200", "打手")
    await services.update_order(
        "200", order2.fixed_seq, take_time=old_time
    )
    await services.check_overdue("200")
    restored = await services.get_order("200", order2.fixed_seq)
    assert restored is not None and restored.status == "未接单"
    assert restored.player_qq == ""


async def test_history(db):
    data = {"total_revenue": 100.0}
    await services.save_history("200", "daily", "2026-08-01", "2026-08-01", "摘要", data)
    rows = await services.list_history("200", history_type="daily")
    assert len(rows) == 1 and rows[0]["summary"] == "摘要"
    rows_range = await services.list_history(
        "200", start_date="2026-08-01", end_date="2026-08-01"
    )
    assert len(rows_range) == 1


def test_build_stats_rank_account():
    orders = [
        {
            "status": "已完成",
            "price": 100.0,
            "creator_qq": "100",
            "creator_nick": "甲",
            "player_qq": "200",
            "player_nick": "乙",
            "order_id": "o1",
            "order_info": "单1",
            "complete_time": "2026-08-01 12:00:00",
        },
        {
            "status": "已完成",
            "price": 50.0,
            "creator_qq": "300",
            "creator_nick": "丙",
            "player_qq": "200",
            "player_nick": "乙",
            "order_id": "o2",
            "order_info": "单2",
            "complete_time": "2026-08-02 12:00:00",
        },
    ]
    commission = services.Commission()
    stat = services.build_stats(orders, commission)
    assert stat["completed"] == 2
    assert stat["revenue"] == pytest.approx(150.0)

    ranked = services.build_rank(orders, commission)
    assert ranked["take"][0]["qq"] == "200"
    assert ranked["take"][0]["count"] == 2
    assert ranked["create"][0]["qq"] == "100"

    account = services.build_account("200", orders, commission)
    assert account["total_orders"] == 2
    assert account["total_earnings"] == pytest.approx(69.0 + 34.5)

    rows = services.build_export_rows(orders, commission)
    assert len(rows) == 2
    assert any("打手分成" in key for key in rows[0])
