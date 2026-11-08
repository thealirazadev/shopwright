"""Merchant approvals API, authenticated with merchant-role tokens."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import text

from app.actions import service
from app.chat import tokens
from app.config import get_settings
from app.connectors.shopify.client import normalize_order_number
from app.connectors.shopify.write import ShopifyWriteClient
from app.crypto import get_cipher
from app.db import get_engine, tenant_connection

router = APIRouter(prefix="/v1/admin", tags=["approvals"])


def merchant_tenant(authorization: Annotated[str, Header()] = "") -> uuid.UUID:
    token = authorization.removeprefix("Bearer ").strip()
    try:
        return tokens.verify(token, get_settings().widget_token_secret, role="merchant")
    except tokens.TokenError as exc:
        raise HTTPException(status_code=401, detail="invalid merchant token") from exc


class StoreWriter:
    """Shopify write access for one store, built from its encrypted install token."""

    def __init__(self, tenant_id: uuid.UUID) -> None:
        with get_engine().connect() as conn:
            row = conn.execute(
                text("SELECT shop_domain, access_token FROM stores WHERE tenant_id = :t"),
                {"t": tenant_id},
            ).first()
        if row is None:
            raise HTTPException(status_code=409, detail="store is not connected")
        self._client = ShopifyWriteClient(row.shop_domain, get_cipher().decrypt(row.access_token))

    def find_order_id(self, order_number: str) -> str | None:
        order = self._client.find_order(normalize_order_number(order_number))
        return order.external_id if order else None

    def cancel_order(self, order_id: str) -> None:
        self._client.cancel_order(order_id)


def writer_factory() -> type[StoreWriter]:
    return StoreWriter


@router.get("/proposals")
def proposals(
    tenant_id: Annotated[uuid.UUID, Depends(merchant_tenant)], status: str = "pending"
) -> list[dict[str, Any]]:
    with tenant_connection(get_engine(), tenant_id) as conn:
        return service.list_proposals(conn, status)


@router.post("/proposals/{proposal_id}/approve")
def approve(
    proposal_id: uuid.UUID,
    tenant_id: Annotated[uuid.UUID, Depends(merchant_tenant)],
    make_writer: Annotated[Any, Depends(writer_factory)],
) -> dict[str, str]:
    with tenant_connection(get_engine(), tenant_id) as conn:
        try:
            status = service.approve(conn, proposal_id, "merchant", make_writer(tenant_id))
        except service.ProposalNotPending as exc:
            raise HTTPException(status_code=409, detail="proposal is not pending") from exc
    return {"status": status}


@router.post("/proposals/{proposal_id}/reject")
def reject(
    proposal_id: uuid.UUID, tenant_id: Annotated[uuid.UUID, Depends(merchant_tenant)]
) -> dict[str, str]:
    with tenant_connection(get_engine(), tenant_id) as conn:
        try:
            service.reject(conn, proposal_id, "merchant")
        except service.ProposalNotPending as exc:
            raise HTTPException(status_code=409, detail="proposal is not pending") from exc
    return {"status": "rejected"}
