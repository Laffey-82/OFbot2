"""共享 HTTP 客户端工具（预构建 SSL 上下文，避免重复加载系统证书）。"""

from __future__ import annotations

import ssl

import httpx

_SHARED_SSL_CONTEXT = ssl.create_default_context()


def make_http_client(timeout: float = 15.0) -> httpx.AsyncClient:
    """构建带共享 SSL 上下文的异步客户端。"""
    return httpx.AsyncClient(timeout=timeout, verify=_SHARED_SSL_CONTEXT)
