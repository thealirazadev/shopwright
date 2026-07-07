"""Proof that row-level security actually isolates tenants (ADR-003).

Connects as a non-superuser role — the same shape as the application's
database role — and verifies that RLS policies hold regardless of what the
application layer does. Requires a running Postgres (docker compose up -d db).
"""

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ProgrammingError

API_DIR = Path(__file__).parents[1]
ADMIN_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://shopwright:shopwright@localhost:5432/shopwright",
)
TEST_ROLE = "shopwright_isolation_test"


@pytest.fixture(scope="module")
def admin_engine() -> Iterator[Engine]:
    engine = create_engine(ADMIN_URL)

    alembic_cfg = Config(str(API_DIR / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(API_DIR / "migrations"))
    command.upgrade(alembic_cfg, "head")

    with engine.begin() as conn:
        conn.execute(
            text(
                f"""
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{TEST_ROLE}') THEN
                        CREATE ROLE {TEST_ROLE} LOGIN PASSWORD '{TEST_ROLE}';
                    END IF;
                END $$
                """
            )
        )
        conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {TEST_ROLE}"))
        conn.execute(text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON products TO {TEST_ROLE}"))
        conn.execute(text("TRUNCATE tenants CASCADE"))

    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def app_engine(admin_engine: Engine) -> Iterator[Engine]:
    url = make_url(ADMIN_URL).set(username=TEST_ROLE, password=TEST_ROLE)
    engine = create_engine(url)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def tenants(admin_engine: Engine) -> tuple[uuid.UUID, uuid.UUID]:
    with admin_engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                INSERT INTO tenants (name, platform)
                VALUES ('tenant-a', 'shopify'), ('tenant-b', 'shopify')
                RETURNING id
                """
            )
        ).fetchall()
    return rows[0][0], rows[1][0]


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
