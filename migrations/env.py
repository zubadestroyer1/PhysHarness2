"""Migration environment independent of runtime model imports."""

import os

from alembic import context
from sqlalchemy import create_engine, pool

config = context.config
url = os.environ.get("PHYSHARNESS_DATABASE_URL") or config.get_main_option("sqlalchemy.url")
if not url:
    raise RuntimeError("Set PHYSHARNESS_DATABASE_URL before running migrations")

if context.is_offline_mode():
    context.configure(
        url=url, target_metadata=None, literal_binds=True, dialect_opts={"paramstyle": "named"}
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    provided = config.attributes.get("connection")
    if provided is not None:
        context.configure(connection=provided, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()
    else:
        engine = create_engine(url, poolclass=pool.NullPool)
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=None)
            with context.begin_transaction():
                context.run_migrations()
        engine.dispose()
