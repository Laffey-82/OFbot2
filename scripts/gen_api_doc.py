"""根据 FastAPI OpenAPI 生成 API.md（自动同步 REST 接口清单）。

用法：py scripts/gen_api_doc.py [openapi.json 路径]
优先使用本地 openapi.json；未提供时尝试读取运行中的服务（127.0.0.1:8080），
最后回退为进程内构建应用获取 schema。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def load_schema(source: str | None) -> dict[str, Any]:
    if source:
        return json.loads(Path(source).read_text(encoding="utf-8"))
    try:
        import httpx

        response = httpx.get("http://127.0.0.1:8080/openapi.json", timeout=5)
        response.raise_for_status()
        return response.json()
    except Exception:
        pass
    import os
    import sys as _sys

    os.chdir(ROOT)
    _sys.path.insert(0, str(ROOT))
    from app.core.config import load_settings
    from app.web.app import create_app

    app = create_app(load_settings(ROOT / "config.yaml"), plugin_manager=None)
    return app.openapi()


def main() -> None:
    source = sys.argv[1] if len(sys.argv) > 1 else None
    schema = load_schema(source)
    paths = schema.get("paths", {})

    lines: list[str] = [
        "# API 文档",
        "",
        (
            "> 本文件由 `scripts/gen_api_doc.py` 依据 FastAPI OpenAPI 自动生成，"
            "接口变化后请运行 `py scripts/gen_api_doc.py` 重新生成。"
        ),
        "",
        "## 鉴权说明",
        "",
        "- 浏览器页面路由：需登录（服务端 Session + CSRF）。",
        (
            "- `/api/v1/*` REST 接口：配置了 `web.api_keys` 时需请求头 `X-API-Key`；"
            "未配置时开放（本地/私域部署默认）。"
        ),
        "",
        "## 接口总览",
        "",
        f"共 {len(paths)} 个路径。",
        "",
    ]

    groups: dict[str, list[tuple[str, str, str]]] = {}
    method_order = ["GET", "POST", "PUT", "DELETE", "PATCH"]
    for path, methods in sorted(paths.items()):
        prefix = path.split("/")[1] if path.count("/") > 1 else ""
        group = f"/{prefix}" if prefix else "/"
        for method in method_order:
            if method.lower() not in methods:
                continue
            item = methods[method.lower()]
            summary = item.get("summary") or item.get("description") or ""
            summary = " ".join(summary.split())[:120]
            groups.setdefault(group, []).append((method, path, summary))

    for group in sorted(groups):
        lines.append(f"### {group or '/'}")
        lines.append("")
        lines.append("| 方法 | 路径 | 说明 |")
        lines.append("| --- | --- | --- |")
        for method, path, summary in groups[group]:
            lines.append(f"| {method} | `{path}` | {summary} |")
        lines.append("")

    target = ROOT / "API.md"
    target.write_text("\n".join(lines), encoding="utf-8")
    print(f"API.md 已生成：{len(paths)} 个路径，{sum(len(v) for v in groups.values())} 个端点")


if __name__ == "__main__":
    main()
