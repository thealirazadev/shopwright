import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Connection, Engine, create_engine, text

from app.config import get_settings


def build_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)


@contextmanager
def tenant_connection(engine: Engine, tenant_id: uuid.UUID) -> Iterator[Connection]:
    """Open a transaction scoped to one tenant.

    Sets the ``app.tenant_id`` GUC transaction-locally so row-level security
    policies apply. Without this, RLS-protected tables return no rows.
    """
    with engine.begin() as conn:
        conn.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(tenant_id)},
        )
        yield conn
