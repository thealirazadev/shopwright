import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url

API_DIR = Path(__file__).parents[1]
ADMIN_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://shopwright:shopwright@localhost:5432/shopwright",
)
TEST_ROLE = "shopwright_isolation_test"


@pytest.fixture(scope="session")
def admin_engine() -> Iterator[Engine]:
    """Superuser connection: runs migrations, provisions the test app role."""
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
        grant = "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public"
        conn.execute(text(f"{grant} TO {TEST_ROLE}"))
        conn.execute(text("TRUNCATE tenants CASCADE"))

    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def app_engine(admin_engine: Engine) -> Iterator[Engine]:
    """Connection as a non-superuser role — the shape the application runs as."""
    url = make_url(ADMIN_URL).set(username=TEST_ROLE, password=TEST_ROLE)
    engine = create_engine(url)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
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


@pytest.fixture
def clean_catalog(admin_engine: Engine) -> Iterator[None]:
    with admin_engine.begin() as conn:
        conn.execute(text("TRUNCATE chunks, policies, products"))
    yield
    with admin_engine.begin() as conn:
        conn.execute(text("TRUNCATE chunks, policies, products"))
