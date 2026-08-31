"""一次性仓库专业化配置：应用 description / topics / homepage 与标签清单。

用法：
    py scripts/repo_setup.py --dry-run   # 仅打印将要执行的请求，不发网络请求
    py scripts/repo_setup.py             # 真实应用（需要 GH_TOKEN）

凭据：环境变量 GH_TOKEN。要求 fine-grained PAT（Administration: Read and write
用于仓库元数据，Issues: Read and write 用于标签）或经典 PAT 的 repo 权限。
脚本绝不回显 token，也不写入磁盘。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = "Laffey-82/OFbot2"
API = "https://api.github.com"

DESCRIPTION = (
    "可扩展的插件化 QQ 机器人框架：多协议多账号、逐群功能开关、"
    "Web 管理后台与插件市场"
)
HOMEPAGE = ""
TOPICS = [
    "qq-bot",
    "onebot",
    "napcat",
    "python",
    "fastapi",
    "plugin",
    "chatbot",
    "qq-nt",
    "asyncio",
    "sqlalchemy",
]

# 与 docs/ISSUE_LABELS.md 对齐：名称 -> (颜色, 说明)
LABELS: dict[str, tuple[str, str]] = {
    "bug": ("d73a4a", "缺陷"),
    "feature": ("0e8a16", "新功能"),
    "enhancement": ("a2eeef", "优化"),
    "question": ("d876e3", "咨询"),
    "core": ("1d76db", "核心层"),
    "adapters": ("0052cc", "协议适配器"),
    "web": ("008672", "Web 后台"),
    "plugins": ("c5def5", "插件生态"),
    "docs": ("7057ff", "文档"),
    "cli": ("e4e669", "命令行"),
    "onebot": ("fbca04", "OneBot 协议"),
    "red": ("f9d0c4", "Red 协议"),
    "satori": ("bfdadc", "Satori 协议"),
    "mirai": ("d93f0b", "Mirai 协议"),
    "qq-official": ("b60205", "QQ 官方机器人"),
    "plugin-submission": ("5319e7", "插件投稿"),
    "plugin-review": ("5319e7", "插件评审"),
    "needs-triage": ("fef2c0", "待分类"),
    "good-first-issue": ("0e8a16", "新手友好"),
    "wontfix": ("ffffff", "不修复"),
    "duplicate": ("cfd3d7", "重复"),
    "security": ("d93f0b", "安全问题"),
    "v1.0.0": ("c2e0c6", "里程碑 v1.0.0"),
    "v1.1.0": ("c2e0c6", "里程碑 v1.1.0"),
    "v1.2.0": ("c2e0c6", "里程碑 v1.2.0"),
    "v1.3.0": ("c2e0c6", "里程碑 v1.3.0"),
}


def _headers(token: str | None) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "ofbot2-repo-setup",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _request(
    method: str,
    url: str,
    *,
    token: str | None,
    payload: dict | None = None,
) -> tuple[int, dict | list]:
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method=method, headers=_headers(token)
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read()
            return resp.status, (json.loads(body) if body else {})
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = json.loads(exc.read().decode("utf-8", "replace")).get(
                "message", ""
            )
        except Exception:
            pass
        raise RuntimeError(
            f"GitHub API {method} {url} 失败（HTTP {exc.code}）：{detail}"
        ) from exc


def _existing_labels(token: str | None) -> set[str]:
    names: set[str] = set()
    page = 1
    while True:
        _, data = _request(
            "GET",
            f"{API}/repos/{REPO}/labels?per_page=100&page={page}",
            token=token,
        )
        if not data:
            break
        names.update(item.get("name", "") for item in data if isinstance(item, dict))
        page += 1
    return names


def plan_requests() -> list[dict]:
    """生成将要执行的请求清单（dry-run 输出）。"""
    return [
        {
            "method": "PATCH",
            "url": f"{API}/repos/{REPO}",
            "payload": {"description": DESCRIPTION, "homepage": HOMEPAGE},
        },
        {
            "method": "PUT",
            "url": f"{API}/repos/{REPO}/topics",
            "payload": {"names": TOPICS},
        },
        *[
            {
                "method": "POST",
                "url": f"{API}/repos/{REPO}/labels",
                "payload": {
                    "name": name,
                    "color": color,
                    "description": desc,
                },
            }
            for name, (color, desc) in sorted(LABELS.items())
        ],
    ]


def apply(token: str) -> None:
    print(f"==> 应用仓库元数据（{REPO}）")
    status, _ = _request(
        "PATCH",
        f"{API}/repos/{REPO}",
        token=token,
        payload={"description": DESCRIPTION, "homepage": HOMEPAGE},
    )
    print(f"    description/homepage 已更新（HTTP {status}）")
    status, _ = _request(
        "PUT",
        f"{API}/repos/{REPO}/topics",
        token=token,
        payload={"names": TOPICS},
    )
    print(f"    topics 已更新（HTTP {status}）：{', '.join(TOPICS)}")

    print("==> 同步标签")
    existing = _existing_labels(token)
    created = 0
    for name, (color, desc) in sorted(LABELS.items()):
        if name in existing:
            continue
        status, _ = _request(
            "POST",
            f"{API}/repos/{REPO}/labels",
            token=token,
            payload={"name": name, "color": color, "description": desc},
        )
        print(f"    创建标签 {name}（HTTP {status}）")
        created += 1
    print(f"    完成：共 {len(LABELS)} 个标签，新建 {created} 个，其余已存在")


def main() -> int:
    parser = argparse.ArgumentParser(description="应用 OFbot2 仓库元数据与标签")
    parser.add_argument(
        "--dry-run", action="store_true", help="仅打印请求清单，不发网络请求"
    )
    args = parser.parse_args()

    if args.dry_run:
        print(f"仓库：{REPO}")
        print(f"description：{DESCRIPTION}")
        print(f"homepage：{HOMEPAGE or '（清空）'}")
        print(f"topics：{', '.join(TOPICS)}")
        print(f"标签（{len(LABELS)} 个）：{', '.join(sorted(LABELS))}")
        return 0

    token = os.environ.get("GH_TOKEN", "").strip()
    if not token:
        print(
            "未设置 GH_TOKEN。请先设置环境变量（fine-grained PAT："
            "Administration RW + Issues RW；或经典 PAT：repo）。",
            file=sys.stderr,
        )
        return 1
    try:
        apply(token)
    except RuntimeError as exc:
        print(f"失败：{exc}", file=sys.stderr)
        return 1
    print("完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
