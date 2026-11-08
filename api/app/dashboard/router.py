"""Read-only merchant dashboard API: conversations, their timelines, and daily cost."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text

from app.actions.router import merchant_tenant
from app.config import get_settings
from app.db import get_engine, tenant_connection

router = APIRouter(prefix="/v1/admin", tags=["dashboard"])

MTOK = Decimal(1_000_000)


@router.get("/conversations")
def conversations(
    tenant_id: Annotated[uuid.UUID, Depends(merchant_tenant)],
    status: Annotated[str | None, Query(pattern="^(open|handoff)$")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[dict[str, Any]]:
    """Most recently active first; `status=handoff` is the handoff queue."""
    with tenant_connection(get_engine(), tenant_id) as conn:
        rows = conn.execute(
            text(
                "SELECT c.id, c.status, c.handoff_reason, c.created_at, c.updated_at, "
                "(SELECT count(*) FROM messages m WHERE m.conversation_id = c.id) AS messages "
                "FROM conversations c WHERE c.tenant_id = :t "
                "AND (CAST(:status AS text) IS NULL OR c.status = :status) "
                "ORDER BY c.updated_at DESC LIMIT :limit"
            ),
            {"t": tenant_id, "status": status, "limit": limit},
        ).mappings()
        return [dict(row) for row in rows]


@router.get("/conversations/{conversation_id}")
def timeline(
    conversation_id: uuid.UUID,
    tenant_id: Annotated[uuid.UUID, Depends(merchant_tenant)],
) -> dict[str, Any]:
    """Messages and trace events (model calls, tool calls) in the order they happened."""
    with tenant_connection(get_engine(), tenant_id) as conn:
        found = (
            conn.execute(
                text(
                    "SELECT id, status, handoff_reason, created_at FROM conversations "
                    "WHERE id = :id AND tenant_id = :t"
                ),
                {"id": conversation_id, "t": tenant_id},
            )
            .mappings()
            .first()
        )
        if found is None:
            raise HTTPException(status_code=404, detail="conversation not found")
        messages = conn.execute(
            text(
                "SELECT role, content, created_at FROM messages "
                "WHERE conversation_id = :id ORDER BY id"
            ),
            {"id": conversation_id},
        ).mappings()
        events = conn.execute(
            text(
                "SELECT turn, kind, name, detail, latency_ms, input_tokens, output_tokens, "
                "created_at FROM traces WHERE conversation_id = :id ORDER BY id"
            ),
            {"id": conversation_id},
        ).mappings()
        return {
            **dict(found),
            "messages": [dict(m) for m in messages],
            "events": [dict(e) for e in events],
        }


@router.get("/costs")
def costs(
    tenant_id: Annotated[uuid.UUID, Depends(merchant_tenant)],
    days: Annotated[int, Query(ge=1, le=90)] = 30,
) -> list[dict[str, Any]]:
    """Model tokens and estimated cost per day, from provider-reported usage in traces."""
    settings = get_settings()
    with tenant_connection(get_engine(), tenant_id) as conn:
        rows = conn.execute(
            text(
                "SELECT (created_at AT TIME ZONE 'UTC')::date AS day, "
                "count(DISTINCT conversation_id) AS conversations, "
                "coalesce(sum(input_tokens), 0) AS input_tokens, "
                "coalesce(sum(output_tokens), 0) AS output_tokens "
                "FROM traces WHERE tenant_id = :t "
                "AND created_at >= (now() AT TIME ZONE 'UTC')::date - (:days - 1) "
                "GROUP BY day ORDER BY day"
            ),
            {"t": tenant_id, "days": days},
        ).mappings()
        result = []
        for row in rows:
            cost = (
                row["input_tokens"] * settings.agent_input_usd_per_mtok
                + row["output_tokens"] * settings.agent_output_usd_per_mtok
            ) / MTOK
            day: date = row["day"]
            result.append({**dict(row), "day": day.isoformat(), "cost_usd": f"{cost:.4f}"})
        return result
