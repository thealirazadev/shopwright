"""Tools the agent may call. All of them read, except handoff, which only flags the conversation.

The tenant is fixed by the connection (RLS), never by tool input.
"""

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Connection, text

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
        "name": "handoff",
        "description": "Hand the conversation to a person. Use when asked, when unsure, or when "
        "the shopper is upset.",
        "input_schema": _schema({"reason": {"type": "string"}}),
    },
]


@dataclass
class ToolContext:
    conn: Connection
    embedder: Embedder
    sources: dict[str, Hit] = field(default_factory=dict)
    handoff_reason: str | None = None

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
    if name == "handoff":
        ctx.handoff_reason = str(args["reason"])
        return json.dumps({"status": "handed_off"})
    raise ToolInputError(f"unknown tool {name}")
