"""Proof that row-level security actually isolates tenants (ADR-003).

Connects as a non-superuser role — the same shape as the application's
database role — and verifies that RLS policies hold regardless of what the
application layer does. Requires a running Postgres (docker compose up -d db).
"""

import uuid

import pytest
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import ProgrammingError


def set_tenant(conn: Connection, tenant_id: uuid.UUID) -> None:
    conn.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": str(tenant_id)},
    )


def insert_product(conn: Connection, tenant_id: uuid.UUID, external_id: str) -> None:
    conn.execute(
        text(
            """
            INSERT INTO products (tenant_id, external_id, title)
            VALUES (:tenant_id, :external_id, 'test product')
            """
        ),
        {"tenant_id": str(tenant_id), "external_id": external_id},
    )


def test_cross_tenant_reads_return_nothing(
    app_engine: Engine, tenants: tuple[uuid.UUID, uuid.UUID]
) -> None:
    tenant_a, tenant_b = tenants
    with app_engine.begin() as conn:
        set_tenant(conn, tenant_a)
        insert_product(conn, tenant_a, "prod-1")

    with app_engine.begin() as conn:
        set_tenant(conn, tenant_b)
        rows = conn.execute(text("SELECT id FROM products")).fetchall()
    assert rows == []

    with app_engine.begin() as conn:
        set_tenant(conn, tenant_a)
        rows = conn.execute(text("SELECT id FROM products")).fetchall()
    assert len(rows) == 1


def test_writing_into_another_tenant_is_rejected(
    app_engine: Engine, tenants: tuple[uuid.UUID, uuid.UUID]
) -> None:
    tenant_a, tenant_b = tenants
    with pytest.raises(ProgrammingError, match="row-level security"):  # noqa: SIM117
        with app_engine.begin() as conn:
            set_tenant(conn, tenant_a)
            insert_product(conn, tenant_b, "prod-2")


def test_no_tenant_context_means_no_rows(
    app_engine: Engine, tenants: tuple[uuid.UUID, uuid.UUID]
) -> None:
    with app_engine.begin() as conn:
        rows = conn.execute(text("SELECT id FROM products")).fetchall()
    assert rows == []
