import os

from sqlalchemy import create_engine, event, pool

from alembic import context
from pricewatch import models  # noqa: F401  (register tables)
from pricewatch.db import Base

config = context.config
target_metadata = Base.metadata


def _migration_pragmas(dbapi_conn, _record) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=OFF")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.close()


def run_migrations_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata,
                      literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = os.environ.get("ALEMBIC_URL") or config.get_main_option("sqlalchemy.url")
    engine = create_engine(url, poolclass=pool.NullPool)
    if engine.dialect.name == "sqlite":
        # Foreign keys must stay OFF during migrations: batch operations rebuild tables
        # (copy, drop, rename) and ON DELETE CASCADE would wipe child rows on the drop.
        event.listen(engine, "connect", _migration_pragmas)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
