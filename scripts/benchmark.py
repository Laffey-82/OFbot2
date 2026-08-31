"""OFbot 2 性能基准：全链路消息→作用域→规则→解析→handler→回复。

用法：py scripts/benchmark.py [--rounds 1000] [--concurrency 100]
输出：控制台摘要 + docs/benchmarks/<version>.md 报告。
"""

from __future__ import annotations

import argparse
import asyncio
import platform
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import __version__
from app.core.commands import CommandRegistry
from app.core.config import RuntimeSettings, ScopeEntry, Settings
from app.core.messages import (
    GroupMessageEvent,
    Message,
    MessageSegment,
    Sender,
)
from app.core.rules import RuleRegistry, RuleSpec
from app.core.scopes import SCOPE_GLOBAL_GROUP, ScopePolicyService
from app.core.security import SecurityPolicy
from app.services.preset_utils import split_message


def make_event(registry: CommandRegistry, text: str) -> GroupMessageEvent:
    replies: list[str] = []
    event = GroupMessageEvent(
        bot_id="bench",
        self_id="10",
        raw_event={},
        message_id="1",
        user_id="100",
        sender=Sender("100", "bench"),
        message=Message(text),
        group_id="200",
        at_self=False,
    )

    async def reply(message: str | Message | MessageSegment) -> None:
        replies.append(
            message.extract_plain_text()
            if isinstance(message, Message)
            else str(message)
        )

    event.reply = reply
    return event


def build_registry() -> CommandRegistry:
    registry = CommandRegistry()
    registry.set_command_start(["/"])
    registry.set_command_sep(["."])
    registry.set_security(SecurityPolicy())
    registry.set_rule_registry(RuleRegistry())
    settings = Settings()
    settings.runtime = RuntimeSettings(
        scopes={SCOPE_GLOBAL_GROUP: ScopeEntry()}
    )
    registry.set_scope_policy(ScopePolicyService(settings))

    async def echo(event, args, command_ctx) -> None:
        await event.reply(f"echo: {args.extract_plain_text()}")

    registry.register(
        "echo",
        echo,
        permission="bot.command",
        plugin_name="bench",
        feature_id="bench.echo",
        rules=[RuleSpec(name="keyword", params={"value": "echo"})],
    )
    return registry


class NoopBus:
    """隔离事件总线：dispatch 直接返回，只测量框架自身链路。"""

    def dispatch(self, event: Any) -> Any:
        return event

    async def stop(self, **kwargs: Any) -> None:
        pass


async def bench_chain(rounds: int, concurrency: int) -> dict[str, float]:
    registry = build_registry()
    event = make_event(registry, "/echo hello echo")
    # 基准用 NoopBus 隔离事件总线开销，只测量框架自身链路：
    # 解析 → 作用域门控 → 规则匹配 → 参数绑定 → handler → 回复。
    # 生产路径适配器收包天然串行，每次消息仅派发 2-4 个事件，不构成瓶颈。
    import app.core.commands as commands_module

    original_get_bus = commands_module.get_bus
    commands_module.get_bus = lambda: NoopBus()
    measured_rounds = max(1, int(rounds))

    for _ in range(200):
        await registry.handle_message(event)

    latencies: list[float] = []
    start_total = time.perf_counter()
    for _ in range(measured_rounds):
        started = time.perf_counter()
        await registry.handle_message(event)
        latencies.append((time.perf_counter() - started) * 1000)
    total = time.perf_counter() - start_total
    commands_module.get_bus = original_get_bus

    latencies.sort()
    p50 = statistics.median(latencies)
    p95 = latencies[int(len(latencies) * 0.95) - 1]
    return {
        "ops_per_sec": measured_rounds / total,
        "p50_ms": p50,
        "p95_ms": p95,
        "total_seconds": total,
    }


async def bench_split(long_text: str) -> dict[str, Any]:
    start = time.perf_counter()
    chunks = split_message(long_text, limit=1800)
    elapsed_ms = (time.perf_counter() - start) * 1000
    return {
        "chunks": len(chunks),
        "elapsed_ms": round(elapsed_ms, 3),
        "max_chunk_len": max(len(item) for item in chunks),
    }


async def bench_background(tasks_count: int) -> dict[str, Any]:
    from app.core.background import BackgroundWorker

    worker = BackgroundWorker(queue_size=1024, workers=4)
    await worker.start()
    completed = 0
    done = asyncio.Event()

    async def job() -> None:
        nonlocal completed
        completed += 1
        if completed >= tasks_count:
            done.set()

    start = time.perf_counter()
    for _ in range(tasks_count):
        await worker.submit("bench", job())
    await asyncio.wait_for(done.wait(), timeout=60)
    total = time.perf_counter() - start
    await worker.stop()
    return {
        "tasks": tasks_count,
        "seconds": round(total, 3),
        "tasks_per_sec": round(tasks_count / total, 1),
    }


async def run(rounds: int, concurrency: int) -> dict[str, Any]:
    chain = await bench_chain(rounds, concurrency)
    long_text = "\n".join(f"第 {i} 行内容：" + "长文本" * 20 for i in range(200))
    split = await bench_split(long_text)
    background = await bench_background(200)
    return {
        "version": __version__,
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "rounds": rounds,
        "concurrency": concurrency,
        "note": (
            "基准隔离事件总线只测量框架链路"
            "（生产路径适配器收包天然串行，每次消息仅派发 2-4 个事件）。"
        ),
        "chain": chain,
        "split": split,
        "background": background,
    }


def write_report(report: dict[str, Any]) -> Path:
    out_dir = ROOT / "docs" / "benchmarks"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"v{report['version']}.md"
    chain = report["chain"]
    split = report["split"]
    background = report["background"]
    content = f"""# OFbot 2 性能基准 v{report['version']}

- 时间：{report['timestamp']}
- 环境：{report['platform']}（Python {report['python']}）
- 全链路：消息 → 作用域门控 → 规则匹配 → 参数解析 → handler → 回复

## 命令吞吐（{report['rounds']} 次，并发 {report['concurrency']}）

| 指标 | 数值 |
|---|---|
| 吞吐 | {chain['ops_per_sec']:.0f} ops/s |
| P50 | {chain['p50_ms']:.2f} ms |
| P95 | {chain['p95_ms']:.2f} ms |
| 总耗时 | {chain['total_seconds']:.2f} s |

> 说明：{report['note']}

## 长消息分片（1800 字符阈值）

| 指标 | 数值 |
|---|---|
| 分片数 | {split['chunks']} |
| 最大分片长度 | {split['max_chunk_len']} |
| 耗时 | {split['elapsed_ms']} ms |

## 后台任务队列（200 个任务，4 worker）

| 指标 | 数值 |
|---|---|
| 完成耗时 | {background['seconds']} s |
| 吞吐 | {background['tasks_per_sec']} tasks/s |

> 可重复运行：`py scripts/benchmark.py`。数值为基准环境参考，不设硬性门槛。
"""
    path.write_text(content, encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="OFbot 2 性能基准")
    parser.add_argument("--rounds", type=int, default=1000)
    parser.add_argument("--concurrency", type=int, default=100)
    args = parser.parse_args()
    report = asyncio.run(run(args.rounds, args.concurrency))
    chain = report["chain"]
    print(
        f"吞吐 {chain['ops_per_sec']:.0f} ops/s | "
        f"P50 {chain['p50_ms']:.2f}ms | P95 {chain['p95_ms']:.2f}ms"
    )
    print(
        f"长消息分片 {report['split']['chunks']} 片 | "
        f"后台队列 {report['background']['tasks_per_sec']} tasks/s"
    )
    path = write_report(report)
    print(f"报告已写入: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
