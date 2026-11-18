"""Shared pytest fixtures."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from waffle_pos.config import AppConfig
from waffle_pos.db.migrate import upgrade_to_head
from waffle_pos.db.seed import seed_if_empty
from waffle_pos.db.session import make_engine, make_session_factory

# ---------- Database fixtures (prefix ``db_``): a migrated, seeded temp SQLite database ----------


@pytest.fixture
def db_engine(tmp_path: Path) -> Iterator[Engine]:
    engine = make_engine(AppConfig(data_dir=tmp_path, start_sync_loop=False))
    upgrade_to_head(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine: Engine) -> Iterator[Session]:
    """A session on the starter menu (18 items, ids 1-18 in menu order). Rolled back afterwards."""
    session = make_session_factory(db_engine)()
    seed_if_empty(session)
    session.flush()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
