import os

from alembic import context
from sqlalchemy import create_engine, pool

DEFAULT_URL = "postgresql+psycopg://shopwright:shopwright@localhost:5432/shopwright"


def get_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_URL)


def run_migrations_offline() -> None:
    context.configure(url=get_url(), literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(get_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
