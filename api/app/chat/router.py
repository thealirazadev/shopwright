"""Chat API: one POST per shopper message. Returns the agent's reply with citations."""

import json
import logging
import uuid
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Connection, text

from app.agent.loop import HANDOFF_MESSAGE, TurnResult, run_turn
from app.agent.model import Model, ModelError, get_model
from app.agent.tools import OrderSource, ToolContext
from app.chat import tokens
from app.config import get_settings
from app.connectors.shopify.client import OrderDoc, ShopifyReadClient
from app.connectors.shopify.oauth import valid_shop_domain
from app.crypto import get_cipher
from app.db import get_engine, tenant_connection
from app.rag.embedder import Embedder, get_embedder

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["chat"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    conversation_id: uuid.UUID | None = None


class ChatResponse(BaseModel):
    conversation_id: uuid.UUID
    reply: str
    citations: list[dict[str, Any]]
    handoff: bool


def tenant_from_token(authorization: Annotated[str, Header()] = "") -> uuid.UUID:
    token = authorization.removeprefix("Bearer ").strip()
    try:
        return tokens.verify(token, get_settings().widget_token_secret)
    except tokens.TokenError as exc:
        raise HTTPException(status_code=401, detail="invalid widget token") from exc


def model_dependency() -> Model:
    try:
        return get_model()
    except ModelError as exc:
        raise HTTPException(status_code=503, detail="assistant is not configured") from exc


class StoreOrders:
    """Read-only order lookup for one store, built lazily from its encrypted install token."""

    def __init__(self, tenant_id: uuid.UUID) -> None:
        self._tenant_id = tenant_id
        self._client: ShopifyReadClient | None = None

    def find_order(self, order_number: str) -> OrderDoc | None:
        if self._client is None:
            with get_engine().connect() as conn:
                row = conn.execute(
                    text("SELECT shop_domain, access_token FROM stores WHERE tenant_id = :t"),
                    {"t": self._tenant_id},
                ).first()
            if row is None:
                return None
            token = get_cipher().decrypt(row.access_token)
            self._client = ShopifyReadClient(row.shop_domain, token)
        return self._client.find_order(order_number)


def order_source_factory() -> Any:
    return StoreOrders


def _load_conversation(
    conn: Connection, tenant_id: uuid.UUID, conversation_id: uuid.UUID | None
) -> tuple[uuid.UUID, str, list[dict[str, Any]], set[str], int]:
    if conversation_id is None:
        new_id: uuid.UUID = conn.execute(
            text("INSERT INTO conversations (tenant_id) VALUES (:t) RETURNING id"),
            {"t": tenant_id},
        ).scalar_one()
        return new_id, "open", [], set(), 0
    row = conn.execute(
        # RLS already scopes this to the token's store; the explicit filter is defense in depth.
        text(
            "SELECT status, verified_orders, verify_attempts FROM conversations "
            "WHERE id = :id AND tenant_id = :t FOR UPDATE"
        ),
        {"id": conversation_id, "t": tenant_id},
    ).first()
    if row is None:  # unknown, or another store's conversation (RLS hides it)
        raise HTTPException(status_code=404, detail="conversation not found")
    history = [
        {"role": row.role, "content": row.content}
        for row in conn.execute(
            text("SELECT role, content FROM messages WHERE conversation_id = :id ORDER BY id"),
            {"id": conversation_id},
        )
    ]
    return conversation_id, str(row.status), history, set(row.verified_orders), row.verify_attempts


def _save_turn(
    conn: Connection,
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    turn: int,
    new_messages: list[dict[str, Any]],
    result: TurnResult,
    ctx: ToolContext,
    reason: str = "agent handoff",
) -> None:
    for message in new_messages:
        conn.execute(
            text(
                "INSERT INTO messages (tenant_id, conversation_id, role, content) "
                "VALUES (:t, :c, :role, CAST(:content AS jsonb))"
            ),
            {
                "t": tenant_id,
                "c": conversation_id,
                "role": message["role"],
                "content": json.dumps(message["content"]),
            },
        )
    for event in result.trace:
        conn.execute(
            text(
                """
                INSERT INTO traces (tenant_id, conversation_id, turn, kind, name, detail,
                                    latency_ms, input_tokens, output_tokens)
                VALUES (:t, :c, :turn, :kind, :name, CAST(:detail AS jsonb),
                        :latency, :tin, :tout)
                """
            ),
            {
                "t": tenant_id,
                "c": conversation_id,
                "turn": turn,
                "kind": event.kind,
                "name": event.name,
                "detail": json.dumps(event.detail),
                "latency": event.latency_ms,
                "tin": event.input_tokens,
                "tout": event.output_tokens,
            },
        )
    conn.execute(
        text(
            "UPDATE conversations SET status = :status, handoff_reason = :reason, "
            "verified_orders = :verified, verify_attempts = :attempts, updated_at = now() "
            "WHERE id = :id"
        ),
        {
            "verified": sorted(ctx.verified_orders),
            "attempts": ctx.verify_attempts,
            "status": "handoff" if result.handoff else "open",
            "reason": None if not result.handoff else reason,
            "id": conversation_id,
        },
    )


def _over_limit(conn: Connection, tenant_id: uuid.UUID, conversation_id: uuid.UUID) -> str | None:
    """Name the spend limit this message would exceed, if any (architecture.md, agent loop)."""
    settings = get_settings()
    if settings.conversation_token_budget:
        used = conn.execute(
            text(
                "SELECT coalesce(sum(input_tokens + output_tokens), 0) FROM traces "
                "WHERE conversation_id = :c"
            ),
            {"c": conversation_id},
        ).scalar_one()
        if used >= settings.conversation_token_budget:
            return "conversation token budget reached"
    if settings.tenant_monthly_cost_cap_usd:
        tokens_in, tokens_out = conn.execute(
            text(
                "SELECT coalesce(sum(input_tokens), 0), coalesce(sum(output_tokens), 0) "
                "FROM traces WHERE tenant_id = :t "
                "AND created_at >= date_trunc('month', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'"
            ),
            {"t": tenant_id},
        ).one()
        spent = (
            tokens_in * settings.agent_input_usd_per_mtok
            + tokens_out * settings.agent_output_usd_per_mtok
        ) / Decimal(1_000_000)
        if spent >= settings.tenant_monthly_cost_cap_usd:
            return "monthly cost cap reached"
    return None


class SessionRequest(BaseModel):
    shop: str = Field(max_length=255)


class SessionResponse(BaseModel):
    token: str
    expires_in: int


@router.post("/widget/session", response_model=SessionResponse)
def widget_session(body: SessionRequest) -> SessionResponse:
    """Exchange an installed shop's domain for a short-lived widget token.

    Public by design: the widget runs on the storefront, so anyone can chat with a store's
    assistant. The token only binds the session to that one store; it grants no merchant access.
    """
    if not valid_shop_domain(body.shop):
        raise HTTPException(status_code=404, detail="unknown store")
    with get_engine().connect() as conn:
        tenant_id = conn.execute(
            text("SELECT tenant_id FROM stores WHERE shop_domain = :shop"), {"shop": body.shop}
        ).scalar()
    if tenant_id is None:
        raise HTTPException(status_code=404, detail="unknown store")
    secret = get_settings().widget_token_secret
    if not secret:
        raise HTTPException(status_code=503, detail="chat is not configured")
    token = tokens.issue(tenant_id, secret)
    return SessionResponse(token=token, expires_in=tokens.DEFAULT_TTL_SECONDS)


@router.post("/chat", response_model=ChatResponse)
def chat(
    body: ChatRequest,
    tenant_id: Annotated[uuid.UUID, Depends(tenant_from_token)],
    model: Annotated[Model, Depends(model_dependency)],
    embedder: Annotated[Embedder, Depends(get_embedder)],
    make_orders: Annotated[Any, Depends(order_source_factory)],
) -> ChatResponse:
    with tenant_connection(get_engine(), tenant_id) as conn:
        conversation_id, status, history, verified, attempts = _load_conversation(
            conn, tenant_id, body.conversation_id
        )
        if status == "handoff":
            return ChatResponse(
                conversation_id=conversation_id, reply=HANDOFF_MESSAGE, citations=[], handoff=True
            )
        limit = _over_limit(conn, tenant_id, conversation_id)
        if limit is not None:
            logger.warning("chat.limit", extra={"tenant_id": str(tenant_id), "limit": limit})
            reply = [{"type": "text", "text": HANDOFF_MESSAGE}]
            new: list[dict[str, Any]] = [
                {"role": "user", "content": body.message},
                {"role": "assistant", "content": reply},
            ]
            turn = sum(1 for m in history if m["role"] == "user" and isinstance(m["content"], str))
            ctx = ToolContext(conn, embedder, verified_orders=verified, verify_attempts=attempts)
            result = TurnResult(text=HANDOFF_MESSAGE, handoff=True)
            _save_turn(conn, tenant_id, conversation_id, turn, new, result, ctx, limit)
            return ChatResponse(
                conversation_id=conversation_id, reply=HANDOFF_MESSAGE, citations=[], handoff=True
            )
        orders: OrderSource = make_orders(tenant_id)
        ctx = ToolContext(
            conn,
            embedder,
            orders=orders,
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            verified_orders=verified,
            verify_attempts=attempts,
        )
        result = run_turn(model, ctx, history, body.message)
        turn = sum(1 for m in history if m["role"] == "user" and isinstance(m["content"], str))
        _save_turn(
            conn, tenant_id, conversation_id, turn, result.messages[len(history) :], result, ctx
        )
    logger.info(
        "chat.turn",
        extra={"conversation_id": str(conversation_id), "tools": result.tool_calls},
    )
    return ChatResponse(
        conversation_id=conversation_id,
        reply=result.text,
        citations=result.citations,
        handoff=result.handoff,
    )
