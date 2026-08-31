from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from sqlalchemy import select

from app.db.base import get_engine, init_db, reset_db_engine, session_factory
from app.db.models import User
from app.db.repositories import UnitOfWork


@pytest.mark.asyncio
async def test_unit_of_work_commits() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = Path(tmp_dir) / "uow.db"
        url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
        await reset_db_engine()
        engine = get_engine(url)
        await init_db(url)

        async with UnitOfWork() as session:
            session.add(User(user_id="u1", nickname="tester"))

        async with session_factory()() as session:
            user = await session.scalar(select(User).where(User.user_id == "u1"))
            assert user is not None
            assert user.nickname == "tester"

        await engine.dispose()
        await reset_db_engine()

