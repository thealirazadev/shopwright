import uuid
from collections.abc import Iterator
from typing import ClassVar

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.actions.router import writer_factory
from app.chat import tokens
from app.config import get_settings
from app.connectors.shopify.client import ShopifyError
from app.main import app

pytestmark = pytest.mark.usefixtures("clean_catalog")

SECRET = "approvals-secret"


class FakeWriter:
    calls: ClassVar[list[str]] = []
    fail = False

    def __init__(self, tenant_id: uuid.UUID) -> None:
        pass

    def find_order_id(self, order_number: str) -> str | None:
        return f"gid://shopify/Order/{order_number}"

    def cancel_order(self, order_id: str) -> None:
        if FakeWriter.fail:
            raise ShopifyError("order already fulfilled")
        FakeWriter.calls.append(order_id)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, app_engine: Engine) -> Iterator[TestClient]:
    monkeypatch.setenv("WIDGET_TOKEN_SECRET", SECRET)
    monkeypatch.setattr("app.actions.router.get_engine", lambda: app_engine)
    get_settings.cache_clear()
    FakeWriter.calls, FakeWriter.fail = [], False
    app.dependency_overrides[writer_factory] = lambda: FakeWriter
    yield TestClient(app)
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def merchant(tenant: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens.issue(tenant, SECRET, role='merchant')}"}


def proposal(admin_engine: Engine, tenant: uuid.UUID, kind: str = "cancel") -> str:
    with admin_engine.begin() as conn:
        conversation = conn.execute(
            text("INSERT INTO conversations (tenant_id) VALUES (:t) RETURNING id"), {"t": tenant}
        ).scalar_one()
        return str(
            conn.execute(
                text(
                    "INSERT INTO action_proposals (tenant_id, conversation_id, kind, order_ref, "
                    "reason) VALUES (:t, :c, :k, '1042', 'test') RETURNING id"
                ),
                {"t": tenant, "c": conversation, "k": kind},
            ).scalar_one()
        )


def test_a_cancellation_executes_exactly_once(
    client: TestClient, admin_engine: Engine, tenants: tuple[uuid.UUID, uuid.UUID]
) -> None:
    pid = proposal(admin_engine, tenants[0])
    url = f"/v1/admin/proposals/{pid}/approve"

    first = client.post(url, headers=merchant(tenants[0]))
    second = client.post(url, headers=merchant(tenants[0]))

    assert first.json() == {"status": "executed"}
    assert second.status_code == 409
    assert FakeWriter.calls == ["gid://shopify/Order/1042"]


def test_a_failed_write_is_recorded_not_retried_silently(
    client: TestClient, admin_engine: Engine, tenants: tuple[uuid.UUID, uuid.UUID]
) -> None:
    FakeWriter.fail = True
    pid = proposal(admin_engine, tenants[0])

    response = client.post(f"/v1/admin/proposals/{pid}/approve", headers=merchant(tenants[0]))

    assert response.json() == {"status": "failed"}
    with admin_engine.connect() as conn:
        error = conn.execute(text("SELECT execution_error FROM action_proposals")).scalar()
    assert error == "order already fulfilled"


def test_refunds_are_approved_for_the_merchant_to_complete(
    client: TestClient, admin_engine: Engine, tenants: tuple[uuid.UUID, uuid.UUID]
) -> None:
    pid = proposal(admin_engine, tenants[0], kind="refund")

    response = client.post(f"/v1/admin/proposals/{pid}/approve", headers=merchant(tenants[0]))

    assert response.json() == {"status": "approved"}
    assert FakeWriter.calls == []


def test_listing_and_rejecting_are_scoped_to_the_merchant_store(
    client: TestClient, admin_engine: Engine, tenants: tuple[uuid.UUID, uuid.UUID]
) -> None:
    pid = proposal(admin_engine, tenants[0])

    other_store = client.post(f"/v1/admin/proposals/{pid}/reject", headers=merchant(tenants[1]))
    own_list = client.get("/v1/admin/proposals", headers=merchant(tenants[0]))
    other_list = client.get("/v1/admin/proposals", headers=merchant(tenants[1]))

    assert other_store.status_code == 409
    assert [p["id"] for p in own_list.json()] == [pid]
    assert other_list.json() == []


def test_widget_tokens_cannot_use_the_merchant_api(
    client: TestClient, tenants: tuple[uuid.UUID, uuid.UUID]
) -> None:
    widget = {"Authorization": f"Bearer {tokens.issue(tenants[0], SECRET)}"}

    assert client.get("/v1/admin/proposals", headers=widget).status_code == 401
