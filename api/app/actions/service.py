"""Merchant decisions on agent proposals. The only path to a Shopify write.

Approval is one conditional update (pending -> approved), so two clicks or two
tabs approve once. Cancellations then run through the Shopify write client.
Refunds and returns are recorded as approved for the merchant to complete in
Shopify admin: amounts and restocking need a person's judgement in v1.
"""

import logging
import uuid
from typing import Any, Protocol

from sqlalchemy import Connection, text

from app.connectors.shopify.client import ShopifyError

logger = logging.getLogger(__name__)


class OrderWriter(Protocol):
    def cancel_order(self, order_id: str) -> None: ...

    def find_order_id(self, order_number: str) -> str | None: ...


class ProposalNotPending(Exception):
    pass


def list_proposals(conn: Connection, status: str = "pending") -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            SELECT id, conversation_id, kind, order_ref, reason, policy_sources, status,
                   decided_by, decided_at, execution_error, created_at
            FROM action_proposals WHERE status = :status ORDER BY created_at
            """
        ),
        {"status": status},
    ).mappings()
    return [dict(row) for row in rows]


def reject(conn: Connection, proposal_id: uuid.UUID, decided_by: str) -> None:
    updated = conn.execute(
        text(
            """
            UPDATE action_proposals
            SET status = 'rejected', decided_by = :by, decided_at = now()
            WHERE id = :id AND status = 'pending'
            """
        ),
        {"id": proposal_id, "by": decided_by},
    ).rowcount
    if not updated:
        raise ProposalNotPending(str(proposal_id))


def approve(conn: Connection, proposal_id: uuid.UUID, decided_by: str, writer: OrderWriter) -> str:
    """Approve once, then execute. Returns the final status."""
    row = conn.execute(
        text(
            """
            UPDATE action_proposals
            SET status = 'approved', decided_by = :by, decided_at = now()
            WHERE id = :id AND status = 'pending'
            RETURNING kind, order_ref
            """
        ),
        {"id": proposal_id, "by": decided_by},
    ).first()
    if row is None:
        raise ProposalNotPending(str(proposal_id))
    if row.kind != "cancel":
        return "approved"

    try:
        order_id = writer.find_order_id(row.order_ref)
        if order_id is None:
            raise ShopifyError("order not found")
        writer.cancel_order(order_id)
    except ShopifyError as exc:
        logger.warning("actions.execute_failed", extra={"proposal_id": str(proposal_id)})
        conn.execute(
            text(
                "UPDATE action_proposals SET status = 'failed', execution_error = :err "
                "WHERE id = :id"
            ),
            {"id": proposal_id, "err": str(exc)[:500]},
        )
        return "failed"
    conn.execute(
        text("UPDATE action_proposals SET status = 'executed' WHERE id = :id"),
        {"id": proposal_id},
    )
    return "executed"
