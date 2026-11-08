"""Shopify product webhooks.

Handled inline for now: one product per call is small. Move to the Redis queue
(ADR-001) if webhook latency or volume says so.
"""

import base64
import hashlib
import hmac
import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import text

from app.config import get_settings
from app.connectors.shopify.client import ProductDoc
from app.db import get_engine, tenant_connection
from app.ingest.sync import delete_product, upsert_product
from app.rag.embedder import get_embedder

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks/shopify", tags=["webhooks"])

PRODUCT_TOPICS = {"products/create", "products/update", "products/delete"}


def verify_webhook(raw_body: bytes, signature: str, secret: str) -> bool:
    digest = hmac.new(secret.encode(), raw_body, hashlib.sha256).digest()
    return hmac.compare_digest(base64.b64encode(digest).decode(), signature)


def _tenant_for_shop(shop: str) -> uuid.UUID | None:
    # stores is control-plane (ADR-003): looked up before any tenant context exists.
    with get_engine().connect() as conn:
        tenant_id: uuid.UUID | None = conn.execute(
            text("SELECT tenant_id FROM stores WHERE shop_domain = :shop"), {"shop": shop}
        ).scalar()
    return tenant_id


def _apply(topic: str, shop: str, payload: dict[str, Any]) -> None:
    tenant_id = _tenant_for_shop(shop)
    if tenant_id is None:
        logger.info("webhook.unknown_shop", extra={"shop": shop})
        return
    with tenant_connection(get_engine(), tenant_id) as conn:
        if topic == "products/delete":
            delete_product(conn, f"gid://shopify/Product/{payload['id']}")
        else:
            upsert_product(conn, tenant_id, shop, ProductDoc.from_webhook(payload), get_embedder())


@router.post("")
async def receive(request: Request) -> dict[str, str]:
    raw_body = await request.body()
    secret = get_settings().shopify_api_secret
    signature = request.headers.get("X-Shopify-Hmac-Sha256", "")
    if not secret or not verify_webhook(raw_body, signature, secret):
        raise HTTPException(status_code=401, detail="invalid webhook signature")

    topic = request.headers.get("X-Shopify-Topic", "")
    if topic not in PRODUCT_TOPICS:
        return {"status": "ignored"}
    shop = request.headers.get("X-Shopify-Shop-Domain", "")
    try:
        payload = json.loads(raw_body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid json") from exc
    await run_in_threadpool(_apply, topic, shop, payload)
    return {"status": "ok"}
