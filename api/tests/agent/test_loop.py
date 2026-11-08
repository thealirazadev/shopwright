import json
import uuid
from collections.abc import Iterator, Sequence
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import Connection, Engine

from app.agent.loop import HANDOFF_MESSAGE, MAX_MODEL_CALLS, run_turn
from app.agent.model import ModelError, ModelReply
from app.agent.tools import ToolContext
from app.connectors.shopify.client import ProductDoc
from app.db import tenant_connection
from app.ingest.sync import upsert_product
from app.rag.embedder import HashingEmbedder

pytestmark = pytest.mark.usefixtures("clean_catalog")


class ScriptedModel:
    """Returns replies in order; each reply may be a function of the messages so far."""

    def __init__(self, *replies: Any) -> None:
        self.replies = list(replies)
        self.seen: list[list[dict[str, Any]]] = []

    def create(
        self, system: str, messages: Sequence[dict[str, Any]], tools: Sequence[dict[str, Any]]
    ) -> ModelReply:
        self.seen.append(list(messages))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        result: ModelReply = reply(messages) if callable(reply) else reply
        return result


def tool_use(name: str, args: dict[str, Any], call_id: str = "t1") -> ModelReply:
    return ModelReply(
        "tool_use", [{"type": "tool_use", "id": call_id, "name": name, "input": args}]
    )


def answer(text: str) -> ModelReply:
    return ModelReply("end_turn", [{"type": "text", "text": text}])


def last_tool_result(messages: Sequence[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = messages[-1]["content"][0]
    return result


@pytest.fixture
def conn(app_engine: Engine, tenants: tuple[uuid.UUID, uuid.UUID]) -> Iterator[Connection]:
    tenant = tenants[0]
    with tenant_connection(app_engine, tenant) as connection:
        doc = ProductDoc(
            external_id="gid://shopify/Product/1",
            title="Merino Wool Beanie",
            description_html="<p>Warm knit hat made from merino wool.</p>",
            handle="merino-wool-beanie",
            price_min=Decimal("25.00"),
            price_max=Decimal("25.00"),
            available=True,
        )
        upsert_product(connection, tenant, "demo.myshopify.com", doc, HashingEmbedder())
        yield connection


def test_answer_cites_only_sources_the_tools_returned(conn: Connection) -> None:
    model = ScriptedModel(
        tool_use("search_catalog", {"query": "warm hat"}),
        lambda messages: answer("Our Merino Wool Beanie is warm [S1]. It also cures colds [S9]."),
    )

    result = run_turn(model, ToolContext(conn, HashingEmbedder()), [], "Do you have a warm hat?")

    assert result.tool_calls == ["search_catalog"]
    assert result.text == "Our Merino Wool Beanie is warm [S1]. It also cures colds ."
    assert [c["title"] for c in result.citations] == ["Merino Wool Beanie"]
    assert result.handoff is False


def test_product_lookup_uses_the_id_from_search(conn: Connection) -> None:
    captured: dict[str, Any] = {}

    def lookup(messages: Sequence[dict[str, Any]]) -> ModelReply:
        results = json.loads(last_tool_result(messages)["content"])["results"]
        return tool_use("get_product", {"product_id": results[0]["product_id"]}, "t2")

    def finish(messages: Sequence[dict[str, Any]]) -> ModelReply:
        captured.update(json.loads(last_tool_result(messages)["content"]))
        return answer("It is $25.00 and in stock.")

    model = ScriptedModel(tool_use("search_catalog", {"query": "beanie"}), lookup, finish)

    run_turn(model, ToolContext(conn, HashingEmbedder()), [], "How much is the beanie?")

    assert captured == {
        "title": "Merino Wool Beanie",
        "price_min": "25.00",
        "price_max": "25.00",
        "in_stock": True,
    }


def test_bad_tool_input_is_returned_to_the_model_as_an_error(conn: Connection) -> None:
    errors: list[dict[str, Any]] = []

    def finish(messages: Sequence[dict[str, Any]]) -> ModelReply:
        errors.append(last_tool_result(messages))
        return answer("Sorry, I could not find that product.")

    model = ScriptedModel(tool_use("get_product", {"product_id": "not-an-id"}), finish)

    result = run_turn(model, ToolContext(conn, HashingEmbedder()), [], "Price of item X?")

    assert errors[0]["is_error"] is True
    assert result.handoff is False


def test_handoff_tool_ends_the_turn(conn: Connection) -> None:
    model = ScriptedModel(tool_use("handoff", {"reason": "shopper asked for a person"}))

    result = run_turn(model, ToolContext(conn, HashingEmbedder()), [], "Let me talk to a human")

    assert (result.handoff, result.text) == (True, HANDOFF_MESSAGE)


def test_model_failure_hands_off_instead_of_erroring(conn: Connection) -> None:
    model = ScriptedModel(ModelError("overloaded"))

    result = run_turn(model, ToolContext(conn, HashingEmbedder()), [], "hello")

    assert result.handoff is True


def test_a_model_that_never_finishes_is_stopped(conn: Connection) -> None:
    model = ScriptedModel(
        *[tool_use("search_catalog", {"query": "x"}, f"t{i}") for i in range(MAX_MODEL_CALLS)]
    )

    result = run_turn(model, ToolContext(conn, HashingEmbedder()), [], "loop forever")

    assert result.handoff is True
    assert len(model.seen) == MAX_MODEL_CALLS
