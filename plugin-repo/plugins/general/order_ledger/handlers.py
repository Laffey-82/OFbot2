"""order_ledger 插件命令处理器。"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any

from app.core.messages import Message, MessageEvent, MessageSegment
from app.core.parsing import tokenize_args
from app.core.plugin import PluginContext

from . import services
from .config import ratio_text

_ctx: PluginContext | None = None


def init(ctx: PluginContext) -> None:
    global _ctx
    _ctx = ctx


def ctx() -> PluginContext:
    if _ctx is None:
        raise RuntimeError("order_ledger handlers not initialized")
    return _ctx


# ---------------------------------------------------------------- 通用守卫

def group_only(func: Callable) -> Callable:
    """仅群聊可用。"""

    @functools.wraps(func)
    async def wrapper(event, args, command_ctx) -> None:
        if not getattr(event, "group_id", ""):
            await event.reply("该指令仅支持在群聊中使用")
            return
        return await func(event, args, command_ctx)

    return wrapper


def admin_only(func: Callable) -> Callable:
    """管理员及以上角色可用（Web「角色管理」按 QQ 分配 admin/superadmin）。"""

    @functools.wraps(func)
    async def wrapper(event, args, command_ctx) -> None:
        if not _is_admin(event):
            await event.reply(
                "【权限不足】该操作需要管理员权限（可在 Web 后台「角色管理」为 QQ 分配 admin 或 superadmin 角色）"
            )
            return
        return await func(event, args, command_ctx)

    return wrapper


def _principal_role(event: MessageEvent) -> str:
    return ctx().permissions.get_principal(str(event.user_id)).role


def _scope_override(event: MessageEvent, permission: str) -> bool | None:
    policy = ctx().scope_policy
    if policy is None:
        return None
    group_id = getattr(event, "group_id", "") or ""
    scope = f"group:{group_id}" if group_id else "private:*"
    return policy.permission_override(permission, scope)


def _is_admin(event: MessageEvent) -> bool:
    if _principal_role(event) in {"admin", "superadmin"}:
        return True
    return _scope_override(event, "order_ledger.admin") is True


def _group_id(event: MessageEvent) -> str:
    return str(getattr(event, "group_id", "") or "")


def _nickname(event: MessageEvent) -> str:
    sender = getattr(event, "sender", None)
    if sender is not None:
        return str(sender.card or sender.nickname or event.user_id)
    return str(event.user_id)


# ---------------------------------------------------------------- 订单指令

@group_only
async def record_order(event: MessageEvent, args: Message, command_ctx) -> None:
    """/录入 <单子信息> <控分> <控dx> <成绩图> <价格> [备注]"""
    text = args.extract_plain_text().strip()
    tokens = tokenize_args(text)
    if len(tokens) < 5:
        await event.reply(
            "【×】格式错误！\n正确格式：/录入 [单子信息] [控分0/1] [控dx0/1] [成绩图0/1] [价格] [备注(可选)]\n"
            "示例：/录入 白系理论 1 0 1 100 官机打"
        )
        return

    remark = ""
    try:
        price = float(tokens[-1])
    except ValueError:
        try:
            price = float(tokens[-2])
        except ValueError:
            await event.reply("【×】参数错误：价格必须是数字，且需放在备注之前")
            return
        remark = tokens[-1]
        tokens = tokens[:-1]

    if price < 0:
        await event.reply("【×】参数错误：价格必须大于或等于 0")
        return
    if len(tokens) < 5:
        await event.reply("【×】参数错误：缺少单子信息")
        return

    need_score_img, control_dx, control_score = tokens[-2], tokens[-3], tokens[-4]
    for flag_name, flag in (
        ("控分", control_score),
        ("控dx", control_dx),
        ("成绩图", need_score_img),
    ):
        if flag not in ("0", "1"):
            await event.reply(f"【×】参数错误：{flag_name} 必须为 0 或 1，当前值：{flag}")
            return
    order_info = " ".join(tokens[:-4])

    try:
        order = await services.create_order(
            _group_id(event),
            order_info=order_info,
            control_score=control_score,
            control_dx=control_dx,
            need_score_img=need_score_img,
            price=price,
            creator_qq=str(event.user_id),
            creator_nick=_nickname(event),
            remark=remark,
        )
    except Exception as exc:
        await event.reply(f"【×】订单录入失败：{exc}")
        return
    await event.reply(
        "【√】订单录入成功！\n" + services.format_order_card(order.as_dict())
    )


@group_only
async def query_orders(event: MessageEvent, args: Message, command_ctx) -> None:
    """/查询 [筛选] [时间] [页码]"""
    parts = tokenize_args(args.extract_plain_text())
    filter_keys: list[str] = []
    page = "1"
    for part in parts:
        if part.isdigit():
            page = part
        else:
            filter_keys.append(part)

    statuses: list[str] | None = None
    mine_qq: str | None = None
    urgent = False
    create_start = create_end = ""
    base_filters = {
        "未接单": "未接单",
        "已接单": "已接单",
        "已完成": "已完成",
        "已取消": "已取消",
        "进行中": None,  # 特殊处理
        "全部": None,
    }

    for key in filter_keys:
        if key == "我的":
            mine_qq = str(event.user_id)
        elif key == "急单":
            urgent = True
        elif key == "进行中":
            statuses = ["未接单", "已接单"]
        elif key in base_filters and key != "全部":
            statuses = [base_filters[key]]
        elif key in ("本日", "今日"):
            create_start = create_end = services.today()
        elif key == "昨日":
            d = services.yesterday()
            create_start = create_end = d
        elif key == "本周":
            create_start, create_end = services.week_range(
                services.config().get("weekly_start_day", 5)
            )

    # 日期范围：两个连续的 8 位数字
    for i in range(len(filter_keys) - 1):
        a, b = filter_keys[i], filter_keys[i + 1]
        if len(a) == 8 and a.isdigit() and len(b) == 8 and b.isdigit():
            create_start = services.parse_date(a)
            create_end = services.parse_date(b)

    orders = await services.list_orders(
        _group_id(event),
        statuses=statuses,
        mine_qq=mine_qq,
        urgent=urgent,
        create_start=create_start,
        create_end=create_end,
    )
    if not orders:
        desc = " ".join(filter_keys) or "订单"
        await event.reply(f"【清单】暂无{desc}数据")
        return

    page_size = int(services.config()["order_settings"].get("page_size", 5))
    try:
        page_no = max(1, int(page))
    except ValueError:
        page_no = 1
    total_pages = max(1, (len(orders) + page_size - 1) // page_size)
    page_no = min(page_no, total_pages)
    start = (page_no - 1) * page_size
    page_orders = orders[start : start + page_size]

    reply = f"订单列表（第{page_no}/{total_pages}页，共{len(orders)}单）\n"
    for order in page_orders:
        reply += "\n" + services.format_order_card(order)
    if total_pages > 1:
        filter_tip = " " + " ".join(filter_keys) if filter_keys else ""
        next_page = page_no + 1 if page_no < total_pages else 1
        reply += (
            f"\n\n分页提示：/查询{filter_tip} {next_page} 查看下一页 | "
            f"/查询{filter_tip} 1 返回第一页"
        )
    await services.reply_multi(event, reply)


@group_only
async def take_order(event: MessageEvent, args: Message, command_ctx) -> None:
    seq = command_ctx.params["seq"]
    ok, message, order = await services.take_order(
        _group_id(event), seq, str(event.user_id), _nickname(event)
    )
    if not ok:
        await event.reply(f"【×】接单失败：{message}")
        return
    reply = (
        Message.text(f"【√】{message}！ ")
        + MessageSegment.at(event.user_id)
        + Message.text("\n" + services.format_order_card(order))
    )
    await event.reply(reply)


@group_only
async def complete_order(event: MessageEvent, args: Message, command_ctx) -> None:
    seq = command_ctx.params["seq"]
    order = await services.get_order(_group_id(event), seq)
    if order is None:
        await event.reply("【×】无效序号！请使用 /查询 查看可用序号")
        return
    user_qq = str(event.user_id)
    if order.status != "已接单":
        await event.reply(
            f"【×】订单当前状态为【{order.status}】，仅「已接单」可完成"
        )
        return
    if not (
        order.creator_qq == user_qq
        or order.player_qq == user_qq
        or _is_admin(event)
    ):
        await event.reply("【×】只有发单人、接单的打手或管理员可以确认")
        return
    updated = await services.update_order(
        _group_id(event),
        seq,
        status="已完成",
        complete_time=services.now_str(),
        confirmer_qq=user_qq,
        confirmer_nick=_nickname(event),
    )
    if updated is None:
        await event.reply("【×】订单不存在")
        return
    reply = (
        Message.text("【√】订单已完成！ ")
        + MessageSegment.at(order.player_qq)
        + Message.text("\n" + services.format_order_card(updated.as_dict()))
    )
    await event.reply(reply)


@group_only
async def cancel_take(event: MessageEvent, args: Message, command_ctx) -> None:
    seq = command_ctx.params["seq"]
    order = await services.get_order(_group_id(event), seq)
    if order is None:
        await event.reply("【×】无效序号！请使用 /查询 查看可用序号")
        return
    if order.status != "已接单":
        await event.reply(
            f"【×】订单当前状态为【{order.status}】，仅「已接单」可取消接单"
        )
        return
    user_qq = str(event.user_id)
    if order.player_qq != user_qq and not _is_admin(event):
        await event.reply("【×】仅接单的打手或管理员可取消接单")
        return
    updated = await services.update_order(
        _group_id(event),
        seq,
        status="未接单",
        player_qq="",
        player_nick="",
        take_time="",
        cancel_take_time=services.now_str(),
    )
    await event.reply(
        "【√】取消接单成功！订单已重置为「未接单」\n"
        + services.format_order_card((updated or order).as_dict())
    )


@group_only
async def my_orders(event: MessageEvent, args: Message, command_ctx) -> None:
    user_qq = str(event.user_id)
    group_id = _group_id(event)
    take_orders = await services.list_orders(group_id, mine_qq=user_qq)
    create_orders = await services.list_orders(group_id, creator_qq=user_qq)
    if not take_orders and not create_orders:
        await event.reply("【清单】暂无你接的或发布的任何订单")
        return

    cfg = services.config()
    commission = services.Commission(cfg.get("commission_ratio"))
    reply = f"我的订单（{services.user_info(user_qq, _nickname(event))}）\n"
    if take_orders:
        order_types = {
            "未完成": [o for o in take_orders if o.get("status") == "已接单"],
            "已完成": [o for o in take_orders if o.get("status") == "已完成"],
            "已取消": [o for o in take_orders if o.get("status") == "已取消"],
        }
        reply += "\n【我的接单（打手）】\n"
        for type_name, orders in order_types.items():
            if orders:
                reply += f"\n{type_name}：{len(orders)} 单\n"
                for order in orders[:3]:
                    reply += "\n" + services.format_order_card(order)
        total_income = sum(
            float(o.get("price", 0) or 0) * commission.ratio["打手"]
            for o in take_orders
            if o.get("status") == "已完成"
        )
        reply += (
            f"\n累计打手收益（{commission.pct('打手')}%）："
            f"{services.money(total_income)}\n"
        )
    if create_orders:
        reply += "\n【我的发布（接单人）】\n"
        status_counts = {
            "未接单": sum(1 for o in create_orders if o.get("status") == "未接单"),
            "已接单": sum(1 for o in create_orders if o.get("status") == "已接单"),
            "已完成": sum(1 for o in create_orders if o.get("status") == "已完成"),
        }
        reply += "  ".join(
            f"{name}：{count} 单" for name, count in status_counts.items()
        )
        reply += f"\n总计发布：{len(create_orders)} 单"
    await services.reply_multi(event, reply)


@group_only
async def remark_order(event: MessageEvent, args: Message, command_ctx) -> None:
    seq = command_ctx.params["seq"]
    content = str(command_ctx.params.get("content", "")).strip()
    order = await services.get_order(_group_id(event), seq)
    if order is None:
        await event.reply("【×】无效序号！请使用 /查询 查看可用序号")
        return
    user_qq = str(event.user_id)
    if order.creator_qq != user_qq and not _is_admin(event):
        await event.reply("【×】仅接单人、管理员或超级管理员可备注")
        return
    updated = await services.update_order(_group_id(event), seq, remark=content)
    await event.reply(
        "【√】备注已更新！\n" + services.format_order_card((updated or order).as_dict())
    )


@group_only
async def change_price(event: MessageEvent, args: Message, command_ctx) -> None:
    seq = command_ctx.params["seq"]
    new_price = float(command_ctx.params["price"])
    if new_price < 0:
        await event.reply("【×】参数错误：价格必须大于或等于 0")
        return
    order = await services.get_order(_group_id(event), seq)
    if order is None:
        await event.reply("【×】无效序号！请使用 /查询 查看可用序号")
        return
    user_qq = str(event.user_id)
    if order.creator_qq != user_qq and not _is_admin(event):
        await event.reply("【×】仅接单人、管理员或超级管理员可修改价格")
        return
    old_price = order.price
    updated = await services.update_order(_group_id(event), seq, price=new_price)
    await event.reply(
        "【√】价格已更新！\n"
        f"订单序号：{seq}\n原价格：{services.money(old_price)}"
        f"\n新价格：{services.money(new_price)}\n"
        + services.format_order_card((updated or order).as_dict())
    )


@group_only
@admin_only
async def delete_order(event: MessageEvent, args: Message, command_ctx) -> None:
    seq = command_ctx.params["seq"]
    order = await services.get_order(_group_id(event), seq)
    if order is None:
        await event.reply("【×】无效序号！请使用 /查询 查看可用序号")
        return
    ok = await services.delete_order(_group_id(event), seq)
    if not ok:
        await event.reply("【×】删除失败，订单不存在")
        return
    await event.reply(
        f"【√】订单已删除！\n{order.order_info} {services.money(order.price)}"
    )


@group_only
@admin_only
async def highlight_order(event: MessageEvent, args: Message, command_ctx) -> None:
    seq = command_ctx.params["seq"]
    updated = await services.update_order(_group_id(event), seq, highlight=True)
    if updated is None:
        await event.reply("【×】无效序号！请使用 /查询 查看可用序号")
        return
    await event.reply(
        "【√】已标记急单！\n" + services.format_order_card(updated.as_dict())
    )


# ---------------------------------------------------------------- 统计/导出/分账

@group_only
async def stats(event: MessageEvent, args: Message, command_ctx) -> None:
    text = args.extract_plain_text().strip()
    group_id = _group_id(event)
    cfg = services.config()
    commission = services.Commission(cfg.get("commission_ratio"))

    start, end, desc = services.parse_time_param(text)
    if not start and not end and desc not in ("全部", ""):
        # 未识别的参数：按旧行为回退到个人统计
        orders = await services.list_orders(group_id, mine_qq=str(event.user_id))
        total = len(orders)
        completed = [o for o in orders if o.get("status") == "已完成"]
        income = sum(
            float(o.get("price", 0) or 0) * commission.ratio["打手"]
            for o in completed
        )
        await event.reply(
            "你的统计\n"
            f"总接单：{total} 单\n已完成：{len(completed)} 单\n"
            f"收益：{services.money(income)}"
        )
        return

    orders = await services.list_orders(
        group_id, complete_start=start, complete_end=end
    )
    orders = [o for o in orders if o.get("status") == "已完成"]
    if not orders:
        await event.reply(f"【清单】暂无{desc or '订单'}数据")
        return
    stat = services.build_stats(orders, commission)
    reply = (
        f"{desc or '统计'}\n"
        f"完成订单：{stat['completed']} 单\n"
        f"总营收：{services.money(stat['revenue'])}\n\n"
        f"接单人分成（{commission.pct('接单人')}%）：\n"
    )
    reply += "\n".join(
        f"• {name}：{item['count']}单 → {services.money(item['amount'])}"
        for name, item in stat["creator_detail"].items()
    )
    reply += f"\n\n打手分成（{commission.pct('打手')}%）：\n"
    reply += "\n".join(
        f"• {name}：{item['count']}单 → {services.money(item['amount'])}"
        for name, item in stat["player_detail"].items()
    )
    reply += (
        f"\n\nOF分成（{commission.pct('OF')}%）：{services.money(stat['of'])}"
        f"\n应急公款（{commission.pct('应急公款')}%）：{services.money(stat['emergency'])}"
    )
    await services.reply_multi(event, reply)


@group_only
@admin_only
async def export_orders(event: MessageEvent, args: Message, command_ctx) -> None:
    text = args.extract_plain_text().strip()
    if not text:
        await event.reply(
            "【×】格式错误！\n格式：/导出订单 [本日/今日/昨日/本周/全部] 或 /导出订单 YYYYMMDD 或 /导出订单 YYYYMMDD YYYYMMDD"
        )
        return
    group_id = _group_id(event)
    cfg = services.config()
    commission = services.Commission(cfg.get("commission_ratio"))
    start, end, desc = services.parse_time_param(text)

    if start == end == "":
        orders = await services.list_orders(group_id)
    else:
        orders = await services.list_orders(
            group_id, complete_start=start, complete_end=end
        )
        orders = [o for o in orders if o.get("status") == "已完成"]
    if not orders:
        await event.reply(f"【清单】暂无{desc or text}数据")
        return

    rows = services.build_export_rows(orders, commission)
    export_service = ctx().services.get("export")
    if export_service is None:
        await event.reply("【×】导出服务不可用")
        return
    try:
        path = export_service.export_excel(
            rows, services.safe_filename(f"导出_{desc or text}_{services.today()}")
        )
    except Exception as exc:
        await event.reply(f"【×】导出失败：{exc}")
        return
    await event.reply(
        Message.text(
            f"【√】导出成功！共{len(orders)}条数据\n文件：{path.name}"
        )
        + MessageSegment.file(file=str(path), name=path.name)
    )


@group_only
@admin_only
async def run_commission(event: MessageEvent, args: Message, command_ctx) -> None:
    text = args.extract_plain_text().strip()
    group_id = _group_id(event)
    if not text:
        start = end = services.yesterday()
        desc = "昨日"
    else:
        start, end, desc = services.parse_time_param(text)
        if not start and not end:
            await event.reply(
                "格式：/分账 或 /分账 本日/今日/昨日/本周 或 /分账 YYYYMMDD 或 /分账 YYYYMMDD YYYYMMDD"
            )
            return
    data, summary = await services.generate_commission(group_id, start, end, desc)
    history_type = "daily" if start == end else "weekly"
    await services.save_history(
        group_id, history_type, start, end, summary, data
    )
    await services.reply_multi(event, summary)
    groups = services.resolve_target_groups()
    if groups:
        await services.send_to_groups(summary, groups)
    await event.reply("【√】分账操作已执行完成")


@group_only
async def commission_history(event: MessageEvent, args: Message, command_ctx) -> None:
    text = args.extract_plain_text().strip()
    group_id = _group_id(event)
    if not text:
        await event.reply(
            "格式：/分账历史 本日/今日/昨日/本周/全部 或 /分账历史 YYYYMMDD 或 /分账历史 YYYYMMDD YYYYMMDD"
        )
        return

    if text == "全部":
        history = await services.list_history(group_id)
        if not history:
            await event.reply("【×】暂无分账历史记录")
            return
        reply = "【分账历史】\n\n全部历史记录：\n\n"
        for item in history:
            if item["history_type"] == "daily":
                reply += f"日期：{item['start_date']}\n{item['summary']}\n\n"
            else:
                reply += (
                    f"周：{item['start_date']} 至 {item['end_date']}\n"
                    f"{item['summary']}\n\n"
                )
        await services.reply_multi(event, reply)
        return

    start, end, desc = services.parse_time_param(text)
    if not start and not end:
        await event.reply("【×】无效的日期参数")
        return
    history_type = "daily" if start == end else "weekly"
    history = await services.list_history(
        group_id, history_type=history_type, start_date=start, end_date=end
    )
    if not history:
        # 无历史时按旧行为即时生成并保存
        data, summary = await services.generate_commission(group_id, start, end, desc)
        await services.save_history(
            group_id, history_type, start, end, summary, data
        )
        history = await services.list_history(
            group_id, history_type=history_type, start_date=start, end_date=end
        )
    if not history:
        await event.reply(f"【×】{start} 至 {end} 无分账历史记录")
        return
    reply = "【分账历史】\n\n"
    for item in history:
        if item["history_type"] == "daily":
            reply += f"日期：{item['start_date']}\n{item['summary']}\n\n"
        else:
            reply += (
                f"时间范围：{item['start_date']} 至 {item['end_date']}\n"
                f"{item['summary']}\n\n"
            )
    await services.reply_multi(event, reply)


@group_only
async def rank(event: MessageEvent, args: Message, command_ctx) -> None:
    parts = tokenize_args(args.extract_plain_text())
    time_range = "全部"
    rank_type = "全部"
    for part in parts:
        if part in ("全部", "本周", "本日"):
            time_range = part
        elif part in ("接单数", "派单数", "总收益"):
            rank_type = part

    group_id = _group_id(event)
    create_start = create_end = ""
    if time_range == "本周":
        create_start, create_end = services.week_range(
            services.config().get("weekly_start_day", 5)
        )
    elif time_range == "本日":
        create_start = create_end = services.today()
    orders = await services.list_orders(
        group_id, create_start=create_start, create_end=create_end
    )
    commission = services.Commission(services.config().get("commission_ratio"))
    ranked = services.build_rank(orders, commission)

    result = f"【{time_range}排行】\n"
    if rank_type in ("全部", "接单数"):
        result += "\n接单数排行：\n"
        if ranked["take"]:
            for i, item in enumerate(ranked["take"], 1):
                result += f"{i}. {item['nick']}（{item['qq']}）- {item['count']}单\n"
        else:
            result += "暂无数据\n"
    if rank_type in ("全部", "派单数"):
        result += "\n派单数排行：\n"
        if ranked["create"]:
            for i, item in enumerate(ranked["create"], 1):
                result += f"{i}. {item['nick']}（{item['qq']}）- {item['count']}单\n"
        else:
            result += "暂无数据\n"
    if rank_type in ("全部", "总收益"):
        result += "\n总收益排行：\n"
        if ranked["income"]:
            for i, item in enumerate(ranked["income"], 1):
                result += (
                    f"{i}. {item['nick']}（{item['qq']}）- "
                    f"{services.money(item['income'])}\n"
                )
        else:
            result += "暂无数据\n"
    await services.reply_multi(event, result)


@group_only
async def account(event: MessageEvent, args: Message, command_ctx) -> None:
    text = args.extract_plain_text().strip()
    group_id = _group_id(event)
    start, end, _ = services.parse_time_param(text)
    orders = await services.list_orders(
        group_id, complete_start=start, complete_end=end
    )
    commission = services.Commission(services.config().get("commission_ratio"))
    data = services.build_account(str(event.user_id), orders, commission)
    reply = (
        "个人账目中心\n"
        f"QQ号：{data['qq']}\n"
        f"总订单数：{data['total_orders']}\n"
        f"总收益：{services.money(data['total_earnings'])}\n"
        f"作为接单人收益：{services.money(data['creator_earnings'])}\n"
        f"作为打手收益：{services.money(data['player_earnings'])}\n"
    )
    if start and end:
        reply += f"时间范围：{start} 至 {end}\n"
    if data["order_records"]:
        reply += "\n最近的订单记录：\n"
        for i, record in enumerate(data["order_records"][:5], 1):
            reply += (
                f"{i}. 订单号：{record['order_id']}\n"
                f"   订单信息：{record['order_info']}\n"
                f"   金额：{services.money(record['price'])}\n"
                f"   角色：{record['role']}\n"
                f"   收益：{services.money(record['earnings'])}\n"
                f"   完成时间：{record['complete_time']}\n\n"
            )
    else:
        reply += "\n暂无订单记录\n"
    await services.reply_multi(event, reply)


# ---------------------------------------------------------------- 帮助/状态

@group_only
async def help_cmd(event: MessageEvent, args: Message, command_ctx) -> None:
    cfg = services.config()
    ratio = cfg.get("commission_ratio", {})
    help_text = f"""订单管理功能帮助

=====================
【基础指令】
=====================
• /录入 [单子信息] [控分0/1] [控dx0/1] [成绩图0/1] [价格] [备注(可选)]
• /查询 [筛选] [时间] [页码] - 筛选：未接单/已接单/我的/急单/进行中/全部
• /接单 [序号] - 接手订单
• /完成 [序号]（或/确认 [序号]）- 确认完成订单
• /我的订单 - 查看我的接单/发布订单
• /取消接单 [序号] - 取消已接订单
• /备注 [序号] [内容] - 修改订单备注
• /改价 [序号] [新价格] - 修改订单价格
• /排行 [时间范围] [排行类型] - 接单数/派单数/总收益
• /账目 [时间范围] - 查看个人分账历史
• /帮助 - 查看帮助

=====================
【管理员指令】
=====================
• /删除订单 [序号] - 删除订单
• /标记急单 [序号] - 标记急单
• /统计 [时间范围] - 查看统计数据
• /导出订单 [时间范围] - 导出订单 Excel
• /分账 [时间范围] - 立即执行分账
• /分账历史 [时间范围] - 查询分账历史

=====================
【分账规则】（当前配置）
=====================
{ratio_text(ratio)}

=====================
【时间参数说明】
=====================
• 快捷参数：本日/今日/昨日/本周/全部
• 单个日期：YYYYMMDD（如：20260801）
• 日期范围：YYYYMMDD YYYYMMDD
• 【本周】从每周{cfg.get('weekly_start_day', 5)}（0=周一…6=周日）起始

管理员角色请在 Web 后台「角色管理」为 QQ 分配；功能开关在「监听环境」页按群控制。
"""
    await services.reply_multi(event, help_text)


@group_only
async def status_cmd(event: MessageEvent, args: Message, command_ctx) -> None:
    group_id = _group_id(event)
    orders = await services.list_orders(group_id)
    total = len(orders)
    pending = sum(1 for o in orders if o.get("status") == "未接单")
    active = sum(1 for o in orders if o.get("status") == "已接单")
    completed = sum(1 for o in orders if o.get("status") == "已完成")
    reply = (
        "🤖 订单管理插件状态\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"📊 订单统计（本群）：\n"
        f"• 总订单数：{total}\n"
        f"• 未接单：{pending}\n"
        f"• 进行中：{active}\n"
        f"• 已完成：{completed}\n"
    )
    if _is_admin(event):
        cfg = services.config()
        reply += (
            "\n⚙️ 分账比例：\n"
            + ratio_text(cfg.get("commission_ratio", {}))
            + "\n\n📡 定时任务通知群："
            + ("、".join(cfg.get("notify_groups") or []) or "（所有启用本功能的群）")
        )
    await event.reply(reply)


# ---------------------------------------------------------------- 纯文本确认监听

async def on_plain_confirm(event: Any) -> None:
    """兼容旧版：群内直接发送「确认 5」或「完成 5」（无斜杠）确认完成订单。"""
    text = str(getattr(event, "message", "") or "").strip()
    parts = text.split(maxsplit=1)
    if len(parts) != 2 or not parts[1].isdigit():
        return
    group_id = str(getattr(event, "group_id", "") or "")
    user_qq = str(getattr(event, "user_id", "") or "")
    if not group_id or not user_qq:
        return
    seq = int(parts[1])
    order = await services.get_order(group_id, seq)
    if order is None or order.status != "已接单":
        return
    raw = getattr(event, "raw_event", {}) or {}
    sender = raw.get("sender", {}) or {}
    nick = sender.get("card") or sender.get("nickname") or user_qq
    if not (
        order.creator_qq == user_qq
        or order.player_qq == user_qq
        or _is_admin_by_role(user_qq)
    ):
        return
    updated = await services.update_order(
        group_id,
        seq,
        status="已完成",
        complete_time=services.now_str(),
        confirmer_qq=user_qq,
        confirmer_nick=str(nick),
    )
    if updated is not None:
        await ctx().send_group(
            group_id,
            Message.text("【√】订单已完成！ ")
            + MessageSegment.at(order.player_qq)
            + Message.text("\n" + services.format_order_card(updated.as_dict())),
        )


def _is_admin_by_role(user_qq: str) -> bool:
    principal = ctx().permissions.get_principal(user_qq)
    return principal.role in {"admin", "superadmin"}
