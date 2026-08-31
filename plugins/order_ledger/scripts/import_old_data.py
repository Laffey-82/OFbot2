"""把旧 OFbot 的订单 JSON 导入 order_ledger 插件（保留固定序号）。

用法（在 OFbot2 项目根目录执行）：
    py plugins/order_ledger/scripts/import_old_data.py \
        --file "C:/path/to/order_ledger.json" --group 1036036588

可选：
    --config config.yaml    # 指定 OFbot2 配置（数据库地址）
    --dry-run               # 只统计不写入
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True, help="旧 OFbot 的 order_ledger.json 路径")
    parser.add_argument("--group", required=True, help="导入到哪个群（如 1036036588）")
    parser.add_argument("--config", default="config.yaml", help="OFbot2 配置文件路径")
    parser.add_argument("--dry-run", action="store_true", help="只统计不写入")
    return parser.parse_args()


async def run(args: argparse.Namespace) -> int:
    from app.core.config import load_settings
    from app.core.plugin import PluginContext
    from app.db.base import get_engine, init_db, session_factory
    from plugins.order_ledger import models, services  # noqa: F401

    settings = None
    config_path = Path(args.config)
    if config_path.exists():
        settings = load_settings(config_path)
    db_url = settings.database.url if settings else "sqlite+aiosqlite:///data/ofbot2.db"

    source = Path(args.file)
    if not source.exists():
        print(f"[FAIL] 文件不存在：{source}")
        return 1
    data = json.loads(source.read_text(encoding="utf-8"))
    orders = data.get("orders", [])
    print(f"源文件：{source}（共 {len(orders)} 条订单）")

    if args.dry_run:
        print("[DRY-RUN] 未写入任何数据")
        return 0

    get_engine(db_url)
    await init_db(db_url)
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

    imported = 0
    skipped = 0
    for order in orders:
        seq = order.get("fixed_seq")
        try:
            await services.create_order(
                args.group,
                order_info=str(order.get("order_info", "")),
                control_score=str(order.get("control_score", "1")),
                control_dx=str(order.get("control_dx", "1")),
                need_score_img=str(order.get("need_score_img", "1")),
                price=float(order.get("price", 0) or 0),
                creator_qq=str(order.get("creator_qq", "")),
                creator_nick=str(order.get("creator_nick", "")),
                remark=str(order.get("remark", "")),
                seq=int(seq) if isinstance(seq, int) and seq > 0 else None,
                extra={
                    "order_id": str(order.get("id", "")),
                    "status": str(order.get("status", "未接单")),
                    "create_time": str(order.get("create_time", "")),
                    "take_time": str(order.get("take_time", "")),
                    "complete_time": str(order.get("complete_time", "")),
                    "cancel_take_time": str(order.get("cancel_take_time", "")),
                    "overdue_restore_time": str(
                        order.get("overdue_restore_time", "")
                    ),
                    "confirmer_qq": str(order.get("confirmer_qq", "")),
                    "confirmer_nick": str(order.get("confirmer_nick", "")),
                    "player_qq": str(order.get("player_qq", "")),
                    "player_nick": str(order.get("player_nick", "")),
                    "highlight": bool(order.get("highlight", False)),
                },
            )
            imported += 1
        except Exception as exc:
            skipped += 1
            print(f"[SKIP] 订单 {seq or order.get('id')}：{exc}")

    print(f"导入完成：新增 {imported} 条，跳过 {skipped} 条（群 {args.group}）")
    print("提示：旧 daily_summary/weekly_summary 摘要未迁移，可在插件中重新生成分账历史。")
    return 0


def main() -> int:
    return asyncio.run(run(parse_args()))


if __name__ == "__main__":
    sys.exit(main())
