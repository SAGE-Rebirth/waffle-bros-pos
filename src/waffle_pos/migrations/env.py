"""Alembic environment. Runs against the engine passed in by ``waffle_pos.db.migrate`` or the CLI URL."""

from alembic import context
from sqlalchemy import Connection, create_engine

from waffle_pos.config import get_config
from waffle_pos.db.models import Base

config = context.config
target_metadata = Base.metadata


def _run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


connection = config.attributes.get("connection")
if connection is not None:
    _run(connection)
else:
    url = config.get_main_option("sqlalchemy.url") or get_config().db_url
    get_config().data_dir.mkdir(parents=True, exist_ok=True)
    with create_engine(url).connect() as conn:
        _run(conn)
