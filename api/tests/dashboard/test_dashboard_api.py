import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.chat import tokens
from app.config import get_settings
from app.main import app

pytestmark = pytest.mark.usefixtures("clean_catalog")

SECRET = "dashboard-secret"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, app_engine: Engine) -> Iterator[TestClient]:
    monkeypatch.setenv("WIDGET_TOKEN_SECRET", SECRET)
    monkeypatch.setenv("AGENT_INPUT_USD_PER_MTOK", "3")
    monkeypatch.setenv("AGENT_OUTPUT_USD_PER_MTOK", "15")
    # The non-superuser app role, so row-level security is in force.
    monkeypatch.setattr("app.dashboard.router.get_engine", lambda: app_engine)
    get_settings.cache_clear()
    yield TestClient(app)
    get_settings.cache_clear()


def merchant(tenant: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens.issue(tenant, SECRET, role='merchant')}"}


def conversation(engine: Engine, tenant: uuid.UUID, status: str = "open") -> str:
    with engine.begin() as conn:
        cid = conn.execute(
            text("INSERT INTO conversations (tenant_id, status) VALUES (:t, :s) RETURNING id"),
            {"t": tenant, "s": status},
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO messages (tenant_id, conversation_id, role, content) VALUES "
                "(:t, :c, 'user', '\"hi\"'), (:t, :c, 'assistant', '[]')"
            ),
            {"t": tenant, "c": cid},
        )
        conn.execute(
            text(
                "INSERT INTO traces (tenant_id, conversation_id, turn, kind, name, latency_ms, "
                "input_tokens, output_tokens) VALUES "
                "(:t, :c, 0, 'model', 'claude', 900, 1000000, 100000), "
                "(:t, :c, 0, 'tool', 'search_products', 40, 0, 0)"
            ),
            {"t": tenant, "c": cid},
        )
        return str(cid)


def test_conversations_list_and_handoff_queue(
    client: TestClient, admin_engine: Engine, tenants: tuple[uuid.UUID, uuid.UUID]
) -> None:
    conversation(admin_engine, tenants[0])
    handoff = conversation(admin_engine, tenants[0], status="handoff")

    everything = client.get("/v1/admin/conversations", headers=merchant(tenants[0])).json()
    queue = client.get(
        "/v1/admin/conversations?status=handoff", headers=merchant(tenants[0])
    ).json()

    assert len(everything) == 2
    assert everything[0]["messages"] == 2
    assert [c["id"] for c in queue] == [handoff]


def test_timeline_orders_messages_and_events(
    client: TestClient, admin_engine: Engine, tenants: tuple[uuid.UUID, uuid.UUID]
) -> None:
    cid = conversation(admin_engine, tenants[0])

    body = client.get(f"/v1/admin/conversations/{cid}", headers=merchant(tenants[0])).json()

    assert [m["role"] for m in body["messages"]] == ["user", "assistant"]
    assert [e["name"] for e in body["events"]] == ["claude", "search_products"]


def test_cost_per_day_uses_configured_prices(
    client: TestClient, admin_engine: Engine, tenants: tuple[uuid.UUID, uuid.UUID]
) -> None:
    conversation(admin_engine, tenants[0])

    [today] = client.get("/v1/admin/costs", headers=merchant(tenants[0])).json()

    assert today["input_tokens"] == 1_000_000
    assert today["cost_usd"] == "4.5000"  # 1M in at $3 + 0.1M out at $15


def test_a_store_cannot_read_another_stores_data(
    client: TestClient, admin_engine: Engine, tenants: tuple[uuid.UUID, uuid.UUID]
) -> None:
    cid = conversation(admin_engine, tenants[0])
    other = merchant(tenants[1])

    assert client.get(f"/v1/admin/conversations/{cid}", headers=other).status_code == 404
    assert client.get("/v1/admin/conversations", headers=other).json() == []
    assert client.get("/v1/admin/costs", headers=other).json() == []


def test_widget_tokens_are_rejected(
    client: TestClient, tenants: tuple[uuid.UUID, uuid.UUID]
) -> None:
    widget = {"Authorization": f"Bearer {tokens.issue(tenants[0], SECRET)}"}

    assert client.get("/v1/admin/conversations", headers=widget).status_code == 401
