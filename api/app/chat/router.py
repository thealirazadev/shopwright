"""Chat API: one POST per shopper message. Returns the agent's reply with citations."""

import json
import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Connection, text

from app.agent.loop import HANDOFF_MESSAGE, TurnResult, run_turn
from app.agent.model import Model, ModelError, get_model
from app.agent.tools import ToolContext
from app.chat import tokens
from app.config import get_settings
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


def _load_conversation(
    conn: Connection, tenant_id: uuid.UUID, conversation_id: uuid.UUID | None
) -> tuple[uuid.UUID, str, list[dict[str, Any]]]:
    if conversation_id is None:
        new_id: uuid.UUID = conn.execute(
            text("INSERT INTO conversations (tenant_id) VALUES (:t) RETURNING id"),
            {"t": tenant_id},
        ).scalar_one()
        return new_id, "open", []
    status = conn.execute(
        # RLS already scopes this to the token's store; the explicit filter is defense in depth.
        text("SELECT status FROM conversations WHERE id = :id AND tenant_id = :t FOR UPDATE"),
        {"id": conversation_id, "t": tenant_id},
    ).scalar()
    if status is None:  # unknown, or another store's conversation (RLS hides it)
        raise HTTPException(status_code=404, detail="conversation not found")
    history = [
        {"role": row.role, "content": row.content}
        for row in conn.execute(
            text("SELECT role, content FROM messages WHERE conversation_id = :id ORDER BY id"),
            {"id": conversation_id},
        )
    ]
    return conversation_id, str(status), history


def _save_turn(
    conn: Connection,
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    turn: int,
    new_messages: list[dict[str, Any]],
    result: TurnResult,
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
            "updated_at = now() WHERE id = :id"
        ),
        {
            "status": "handoff" if result.handoff else "open",
            "reason": None if not result.handoff else "agent handoff",
            "id": conversation_id,
        },
    )


@router.post("/chat", response_model=ChatResponse)
def chat(
    body: ChatRequest,
    tenant_id: Annotated[uuid.UUID, Depends(tenant_from_token)],
    model: Annotated[Model, Depends(model_dependency)],
    embedder: Annotated[Embedder, Depends(get_embedder)],
) -> ChatResponse:
    with tenant_connection(get_engine(), tenant_id) as conn:
        conversation_id, status, history = _load_conversation(conn, tenant_id, body.conversation_id)
        if status == "handoff":
            return ChatResponse(
                conversation_id=conversation_id, reply=HANDOFF_MESSAGE, citations=[], handoff=True
            )
        result = run_turn(model, ToolContext(conn, embedder), history, body.message)
        turn = sum(1 for m in history if m["role"] == "user" and isinstance(m["content"], str))
        _save_turn(conn, tenant_id, conversation_id, turn, result.messages[len(history) :], result)
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
