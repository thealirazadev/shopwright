import json
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, Engine, text

from app.agent.tools import MAX_VERIFY_ATTEMPTS, ToolContext, ToolInputError, run_tool
from app.connectors.shopify.client import OrderDoc
from app.db import tenant_connection
from app.rag.embedder import HashingEmbedder

pytestmark = pytest.mark.usefixtures("clean_catalog")

ORDER = OrderDoc(
    external_id="gid://shopify/Order/9",
    number="1042",
    email="sam@example.com",
    created_at="2026-11-01T10:00:00Z",
    financial_status="PAID",
    fulfillment_status="FULFILLED",
    total="45.00",
    currency="USD",
    items=[{"title": "Leather Wallet", "quantity": 1}],
    tracking=[{"company": "UPS", "number": "1Z999", "url": None}],
)


class FakeOrders:
    def find_order(self, order_number: str) -> OrderDoc | None:
        return ORDER if order_number == "1042" else None


@pytest.fixture
def ctx(app_engine: Engine, tenants: tuple[uuid.UUID, uuid.UUID]) -> Iterator[ToolContext]:
    tenant = tenants[0]
    with tenant_connection(app_engine, tenant) as conn:
        conversation = conn.execute(
            text("INSERT INTO conversations (tenant_id) VALUES (:t) RETURNING id"), {"t": tenant}
        ).scalar_one()
        yield ToolContext(
            conn,
            HashingEmbedder(),
            orders=FakeOrders(),
            conversation_id=conversation,
            tenant_id=tenant,
        )


def call(ctx: ToolContext, name: str, **args: str) -> dict[str, object]:
    result: dict[str, object] = json.loads(run_tool(ctx, name, args))
    return result


def test_wrong_email_and_unknown_order_look_the_same(ctx: ToolContext) -> None:
    wrong_email = call(ctx, "verify_customer", order_number="#1042", email="eve@example.com")
    no_order = call(ctx, "verify_customer", order_number="9999", email="sam@example.com")

    assert (
        wrong_email
        == no_order
        == {
            "verified": False,
            "message": "Those details did not match an order.",
        }
    )
    assert ctx.verified_orders == set()


def test_order_data_requires_verification_in_this_conversation(ctx: ToolContext) -> None:
    with pytest.raises(ToolInputError, match="not verified"):
        run_tool(ctx, "get_order", {"order_number": "1042"})

    assert call(ctx, "verify_customer", order_number="#1042", email=" Sam@Example.com ")["verified"]
    order = call(ctx, "get_order", order_number="1042")

    assert order["fulfillment_status"] == "FULFILLED"
    assert "email" not in order


def test_verification_attempts_are_capped(ctx: ToolContext) -> None:
    for _ in range(MAX_VERIFY_ATTEMPTS):
        call(ctx, "verify_customer", order_number="1042", email="guess@example.com")

    with pytest.raises(ToolInputError, match="too many"):
        run_tool(ctx, "verify_customer", {"order_number": "1042", "email": "sam@example.com"})


def test_proposals_need_a_verified_order_and_only_record_a_request(
    ctx: ToolContext, admin_engine: Engine
) -> None:
    args = {"kind": "refund", "order_number": "1042", "reason": "arrived damaged"}
    with pytest.raises(ToolInputError, match="not verified"):
        run_tool(ctx, "propose_action", args)

    call(ctx, "verify_customer", order_number="1042", email="sam@example.com")
    result = json.loads(run_tool(ctx, "propose_action", args))

    assert result["status"] == "pending_review"
    conn: Connection = ctx.conn
    row = conn.execute(text("SELECT kind, order_ref, status FROM action_proposals")).one()
    assert tuple(row) == ("refund", "1042", "pending")
