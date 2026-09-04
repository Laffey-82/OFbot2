from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


_engine: AsyncEngine | None = None
_engine_url: str | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


async def reset_db_engine() -> None:
    """关闭旧引擎（归还/释放连接池）后重置全局状态。

    直接丢弃引用会让 AsyncEngine 连同池内连接被垃圾回收，触发
    SQLAlchemy "non-checked-in connection" 警告；显式 dispose 可避免。
    """
    global _engine, _engine_url, _session_factory
    engine = _engine
    _engine = None
    _engine_url = None
    _session_factory = None
    if engine is not None:
        try:
            await engine.dispose()
        except Exception:
            # 引擎已不可用（如测试中的临时数据库）时忽略，仅保证引用被清空。
            pass


def resolve_database_url(url: str) -> str:
    if url.startswith("sqlite+aiosqlite:///") and ":///" in url:
        raw_path = url.split("sqlite+aiosqlite:///", 1)[1]
        path = Path(raw_path)
        if not path.is_absolute():
            project_root = Path(__file__).resolve().parents[2]
            path = project_root / path
        return f"sqlite+aiosqlite:///{path.as_posix()}"
    return url


def resolve_sqlite_path(url: str) -> Path:
    """从 SQLite 连接 URL 解析出本地文件绝对路径。

    支持 sqlite+aiosqlite:/// 和 sqlite:/// 两种前缀；非 SQLite URL
    时抛出 ValueError。
    """
    for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
        if url.startswith(prefix):
            raw = url[len(prefix) :]
            path = Path(raw)
            if not path.is_absolute():
                project_root = Path(__file__).resolve().parents[2]
                path = project_root / path
            return path
    raise ValueError(f"not a sqlite URL: {url}")


def get_engine(url: str) -> AsyncEngine:
    global _engine, _engine_url, _session_factory
    resolved = resolve_database_url(url)
    if _engine is not None and _engine_url != resolved:
        import asyncio

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_dispose_engine(_engine))
        except RuntimeError:
            pass
        _engine = None
        _session_factory = None
    if _engine is None:
        _engine = create_async_engine(
            resolved,
            echo=False,
            future=True,
        )
        _engine_url = resolved
        _session_factory = async_sessionmaker(
            _engine,
            expire_on_commit=False,
            autoflush=False,
        )
    return _engine


async def _dispose_engine(engine: AsyncEngine) -> None:
    """显式 dispose 旧引擎，释放连接池。"""
    try:
        await engine.dispose()
    except Exception:
        pass


def session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError("database engine has not been initialized")
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    async with session_factory()() as session:
        yield session


async def init_db(url: str, extra_models: list[type[Base]] | None = None) -> None:
    engine = get_engine(url)
    from app.db import models  # noqa: F401

    # 确保 ctx.register_models 注册的模型表已进入元数据（防御性，通常类定义即注册）
    for model in extra_models or []:
        table = getattr(model, "__table__", None)
        if table is not None and table.name not in Base.metadata.tables:
            try:
                Base.metadata._add_table(table.name, table.schema, table)
            except (AttributeError, TypeError):
                Base.metadata.add(table)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
