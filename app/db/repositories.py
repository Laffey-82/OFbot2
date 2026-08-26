from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import session_factory


class UnitOfWork:
    def __init__(self) -> None:
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> AsyncSession:
        self._session = session_factory()()
        return self._session

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._session is None:
            return
        if exc_type is not None:
            await self._session.rollback()
        else:
            await self._session.commit()
        await self._session.close()


@asynccontextmanager
async def unit_of_work() -> AsyncIterator[AsyncSession]:
    async with UnitOfWork() as session:
        yield session

