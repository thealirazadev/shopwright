import uuid
from collections.abc import Iterator, Sequence
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.agent.model import ModelReply
from app.chat import tokens
from app.chat.router import model_dependency
from app.config import get_settings
from app.main import app
from app.rag.embedder import HashingEmbedder, get_embedder

pytestmark = pytest.mark.usefixtures("clean_catalog")

SECRET = "chat-test-secret"


class EchoModel:
    """Answers every message, counting how many prior messages it was given."""

    def __init__(self) -> None:
        self.history_sizes: list[int] = []

    def create(
        self, system: str, messages: Sequence[dict[str, Any]], tools: Sequence[dict[str, Any]]
    ) -> ModelReply:
        self.history_sizes.append(len(messages))
        last = messages[-1]["content"]
        if "human" in str(last):
            return ModelReply(
                "tool_use",
                [{"type": "tool_use", "id": "h1", "name": "handoff", "input": {"reason": "asked"}}],
            )
        return ModelReply("end_turn", [{"type": "text", "text": f"You said: {last}"}], 7, 3)


@pytest.fixture
def model() -> EchoModel:
    return EchoModel()


@pytest.fixture
def client(
    monkeypatch: pytest.MonkeyPatch, model: EchoModel, app_engine: Engine
) -> Iterator[TestClient]:
    monkeypatch.setenv("WIDGET_TOKEN_SECRET", SECRET)
    # Run the endpoint as the non-superuser app role so row-level security is in force.
    monkeypatch.setattr("app.chat.router.get_engine", lambda: app_engine)
    get_settings.cache_clear()
    app.dependency_overrides[model_dependency] = lambda: model
    app.dependency_overrides[get_embedder] = HashingEmbedder
    yield TestClient(app)
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def auth(tenant: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens.issue(tenant, SECRET)}"}


def test_a_conversation_keeps_its_history_and_traces(
    client: TestClient,
    model: EchoModel,
    admin_engine: Engine,
    tenants: tuple[uuid.UUID, uuid.UUID],
) -> None:
    first = client.post("/v1/chat", headers=auth(tenants[0]), json={"message": "hello"})
    conversation_id = first.json()["conversation_id"]
    second = client.post(
        "/v1/chat",
        headers=auth(tenants[0]),
        json={"message": "again", "conversation_id": conversation_id},
    )

    assert first.status_code == second.status_code == 200
    assert second.json()["reply"] == "You said: again"
    assert model.history_sizes == [1, 3]
    with admin_engine.connect() as conn:
        messages = conn.execute(text("SELECT count(*) FROM messages")).scalar()
        tokens_in = conn.execute(text("SELECT sum(input_tokens) FROM traces")).scalar()
    assert (messages, tokens_in) == (4, 14)


def test_handoff_stops_the_agent_for_the_rest_of_the_conversation(
    client: TestClient, model: EchoModel, tenants: tuple[uuid.UUID, uuid.UUID]
) -> None:
    first = client.post("/v1/chat", headers=auth(tenants[0]), json={"message": "a human please"})
    conversation_id = first.json()["conversation_id"]
    later = client.post(
        "/v1/chat",
        headers=auth(tenants[0]),
        json={"message": "hello?", "conversation_id": conversation_id},
    )

    assert first.json()["handoff"] is True
    assert later.json()["handoff"] is True
    assert len(model.history_sizes) == 1


def test_another_store_cannot_continue_the_conversation(
    client: TestClient, tenants: tuple[uuid.UUID, uuid.UUID]
) -> None:
    first = client.post("/v1/chat", headers=auth(tenants[0]), json={"message": "hello"})

    response = client.post(
        "/v1/chat",
        headers=auth(tenants[1]),
        json={"message": "hi", "conversation_id": first.json()["conversation_id"]},
    )

    assert response.status_code == 404


def test_requests_without_a_valid_token_are_rejected(client: TestClient) -> None:
    response = client.post(
        "/v1/chat", headers={"Authorization": "Bearer nope"}, json={"message": "hi"}
    )

    assert response.status_code == 401


def test_an_installed_shop_gets_a_widget_token_for_its_own_store(
    client: TestClient, admin_engine: Engine, tenants: tuple[uuid.UUID, uuid.UUID]
) -> None:
    with admin_engine.begin() as conn:
        conn.execute(text("DELETE FROM stores WHERE shop_domain = 'widget-a.myshopify.com'"))
        conn.execute(
            text(
                "INSERT INTO stores (tenant_id, shop_domain, access_token) "
                "VALUES (:t, 'widget-a.myshopify.com', 'x')"
            ),
            {"t": tenants[0]},
        )

    response = client.post("/v1/widget/session", json={"shop": "widget-a.myshopify.com"})
    unknown = client.post("/v1/widget/session", json={"shop": "nobody.myshopify.com"})
    invalid = client.post("/v1/widget/session", json={"shop": "evil.com"})

    assert response.status_code == 200
    assert tokens.verify(response.json()["token"], SECRET) == tenants[0]
    assert unknown.status_code == invalid.status_code == 404
