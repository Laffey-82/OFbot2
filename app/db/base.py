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
_session_factory: async_sessionmaker[AsyncSession] | None = None


def reset_db_engine() -> None:
    global _engine, _session_factory
    _engine = None
    _session_factory = None


def resolve_database_url(url: str) -> str:
    if url.startswith("sqlite+aiosqlite:///") and ":///" in url:
        raw_path = url.split("sqlite+aiosqlite:///", 1)[1]
        path = Path(raw_path)
        if not path.is_absolute():
            project_root = Path(__file__).resolve().parents[2]
            path = project_root / path
        return f"sqlite+aiosqlite:///{path.as_posix()}"
    return url


def get_engine(url: str) -> AsyncEngine:
    global _engine, _session_factory
    if _engine is None:
        _engine = create_async_engine(
            resolve_database_url(url),
            echo=False,
            future=True,
        )
        _session_factory = async_sessionmaker(
            _engine,
            expire_on_commit=False,
            autoflush=False,
        )
    return _engine


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

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
