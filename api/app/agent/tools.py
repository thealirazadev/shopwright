"""Tools the agent may call.

They read, except handoff (flags the conversation) and propose_action (records a
proposal for a merchant to approve). Nothing here can change an order. The
tenant is fixed by the connection (RLS), never by tool input, and order access
is checked in code against the orders verified in this conversation.
"""

import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy import Connection, text

from app.connectors.shopify.client import OrderDoc, ShopifyError, normalize_order_number
from app.rag.embedder import Embedder
from app.rag.retrieval import Hit, search


def _schema(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


_QUERY = {"type": "string", "description": "What to look for, in the shopper's words"}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "search_catalog",
        "description": "Search the store's products. Returns matching excerpts with source ids.",
        "input_schema": _schema({"query": _QUERY}),
    },
    {
        "name": "get_product",
        "description": "Current price and stock for one product, by the product_id from a search.",
        "input_schema": _schema({"product_id": {"type": "string"}}),
    },
    {
        "name": "search_policies",
        "description": "Search the store's policies: returns, refunds, shipping, privacy, terms.",
        "input_schema": _schema({"query": _QUERY}),
    },
    {
        "name": "verify_customer",
        "description": "Verify the shopper owns an order. Needs the order number and the email "
        "used on the order. Required before get_order or propose_action.",
        "input_schema": _schema({"order_number": {"type": "string"}, "email": {"type": "string"}}),
    },
    {
        "name": "get_order",
        "description": "Status, items, and tracking for an order verified in this conversation.",
        "input_schema": _schema({"order_number": {"type": "string"}}),
    },
    {
        "name": "propose_action",
        "description": "Ask the store team to refund, return, or cancel a verified order. This "
        "does not do it: a person reviews every request. Cite the policy that applies.",
        "input_schema": _schema(
            {
                "kind": {"type": "string", "enum": ["refund", "return", "cancel"]},
                "order_number": {"type": "string"},
                "reason": {"type": "string"},
                "policy_sources": {"type": "array", "items": {"type": "string"}},
            }
        ),
    },
    {
        "name": "handoff",
        "description": "Hand the conversation to a person. Use when asked, when unsure, or when "
        "the shopper is upset.",
        "input_schema": _schema({"reason": {"type": "string"}}),
    },
]


MAX_VERIFY_ATTEMPTS = 3


class OrderSource(Protocol):
    def find_order(self, order_number: str) -> OrderDoc | None: ...


@dataclass
class ToolContext:
    conn: Connection
    embedder: Embedder
    orders: OrderSource | None = None
    conversation_id: uuid.UUID | None = None
    tenant_id: uuid.UUID | None = None
    verified_orders: set[str] = field(default_factory=set)
    verify_attempts: int = 0
    sources: dict[str, Hit] = field(default_factory=dict)
    handoff_reason: str | None = None
    proposals: list[uuid.UUID] = field(default_factory=list)

    def _verified(self, order_number: str) -> str:
        number = normalize_order_number(order_number)
        if number not in self.verified_orders:
            raise ToolInputError(
                "this order is not verified in this conversation; ask for the order number and "
                "email, then call verify_customer"
            )
        return number

    def _cite(self, hits: list[Hit]) -> list[dict[str, Any]]:
        items = []
        for hit in hits:
            label = next((k for k, v in self.sources.items() if v.chunk_id == hit.chunk_id), None)
            if label is None:
                label = f"S{len(self.sources) + 1}"
                self.sources[label] = hit
            item: dict[str, Any] = {"source": label, "title": hit.title, "content": hit.content}
            if hit.source_type == "product":
                item["product_id"] = str(hit.source_id)
            items.append(item)
        return items


class ToolInputError(Exception):
    pass


def run_tool(ctx: ToolContext, name: str, args: dict[str, Any]) -> str:
    """Execute one tool call and return its result as JSON text for the model."""
    if name == "search_catalog":
        hits = search(ctx.conn, str(args["query"]), ctx.embedder, source_type="product")
        return json.dumps({"results": ctx._cite(hits)})
    if name == "search_policies":
        hits = search(ctx.conn, str(args["query"]), ctx.embedder, source_type="policy")
        return json.dumps({"results": ctx._cite(hits)})
    if name == "get_product":
        try:
            product_id = uuid.UUID(str(args["product_id"]))
        except ValueError as exc:
            raise ToolInputError("product_id must be an id returned by search_catalog") from exc
        row = ctx.conn.execute(
            text("SELECT title, price_min, price_max, available FROM products WHERE id = :id"),
            {"id": product_id},
        ).first()
        if row is None:
            raise ToolInputError("no such product")
        return json.dumps(
            {
                "title": row.title,
                "price_min": str(row.price_min) if row.price_min is not None else None,
                "price_max": str(row.price_max) if row.price_max is not None else None,
                "in_stock": row.available,
            }
        )
    if name == "verify_customer":
        return _verify_customer(ctx, str(args["order_number"]), str(args["email"]))
    if name == "get_order":
        number = ctx._verified(str(args["order_number"]))
        order = _find(ctx, number)
        if order is None:
            raise ToolInputError("the order could not be loaded; offer a handoff")
        return json.dumps(
            {
                "order_number": order.number,
                "placed_at": order.created_at,
                "payment_status": order.financial_status,
                "fulfillment_status": order.fulfillment_status,
                "total": f"{order.total} {order.currency}",
                "items": order.items,
                "tracking": order.tracking,
            }
        )
    if name == "propose_action":
        return _propose(ctx, args)
    if name == "handoff":
        ctx.handoff_reason = str(args["reason"])
        return json.dumps({"status": "handed_off"})
    raise ToolInputError(f"unknown tool {name}")


def _find(ctx: ToolContext, number: str) -> OrderDoc | None:
    if ctx.orders is None:
        raise ToolInputError("order lookup is not available for this store; offer a handoff")
    try:
        return ctx.orders.find_order(number)
    except ShopifyError as exc:
        raise ToolInputError(
            "the store could not be reached; try again or offer a handoff"
        ) from exc


def _verify_customer(ctx: ToolContext, order_number: str, email: str) -> str:
    if ctx.verify_attempts >= MAX_VERIFY_ATTEMPTS:
        raise ToolInputError("too many verification attempts; offer a handoff instead")
    ctx.verify_attempts += 1
    number = normalize_order_number(order_number)
    order = _find(ctx, number)
    # Same answer for "no such order" and "wrong email", so orders cannot be probed.
    if order is None or order.email.strip().lower() != email.strip().lower():
        return json.dumps({"verified": False, "message": "Those details did not match an order."})
    ctx.verified_orders.add(number)
    return json.dumps({"verified": True, "order_number": number})


def _propose(ctx: ToolContext, args: dict[str, Any]) -> str:
    number = ctx._verified(str(args["order_number"]))
    kind = str(args["kind"])
    if kind not in ("refund", "return", "cancel"):
        raise ToolInputError("kind must be refund, return, or cancel")
    if ctx.conversation_id is None or ctx.tenant_id is None:
        raise ToolInputError("requests cannot be recorded here; offer a handoff")
    proposal_id: uuid.UUID = ctx.conn.execute(
        text(
            """
            INSERT INTO action_proposals
                (tenant_id, conversation_id, kind, order_ref, reason, policy_sources)
            VALUES (:t, :c, :kind, :order, :reason, CAST(:sources AS jsonb))
            RETURNING id
            """
        ),
        {
            "t": ctx.tenant_id,
            "c": ctx.conversation_id,
            "kind": kind,
            "order": number,
            "reason": str(args["reason"])[:1000],
            "sources": json.dumps([str(s) for s in args.get("policy_sources") or []]),
        },
    ).scalar_one()
    ctx.proposals.append(proposal_id)
    return json.dumps(
        {
            "status": "pending_review",
            "message": "Recorded. A member of the store team will review this request.",
        }
    )
