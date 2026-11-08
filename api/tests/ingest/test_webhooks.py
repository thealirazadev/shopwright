import base64
import hashlib
import hmac
import json
import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.config import get_settings
from app.main import app

pytestmark = pytest.mark.usefixtures("clean_catalog")

SECRET = "webhook-test-secret"
SHOP = "webhook-test.myshopify.com"

PAYLOAD = {
    "id": 42,
    "admin_graphql_api_id": "gid://shopify/Product/42",
    "title": "Rain Jacket",
    "body_html": "<p>Waterproof and packable.</p>",
    "handle": "rain-jacket",
    "status": "active",
    "variants": [{"price": "89.00", "inventory_management": None}],
}


@pytest.fixture
def client(
    monkeypatch: pytest.MonkeyPatch, admin_engine: Engine, tenants: tuple[uuid.UUID, uuid.UUID]
) -> Iterator[TestClient]:
    monkeypatch.setenv("SHOPIFY_API_SECRET", SECRET)
    get_settings.cache_clear()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO stores (tenant_id, shop_domain, access_token) "
                "VALUES (:t, :s, 'x') ON CONFLICT (shop_domain) DO NOTHING"
            ),
            {"t": tenants[0], "s": SHOP},
        )
    yield TestClient(app)
    get_settings.cache_clear()


def post(client: TestClient, topic: str, payload: dict[str, object], secret: str = SECRET) -> int:
    body = json.dumps(payload).encode()
    signature = base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest())
    response = client.post(
        "/webhooks/shopify",
        content=body,
        headers={
            "X-Shopify-Hmac-Sha256": signature.decode(),
            "X-Shopify-Topic": topic,
            "X-Shopify-Shop-Domain": SHOP,
        },
    )
    return int(response.status_code)


def titles(admin_engine: Engine) -> list[str]:
    with admin_engine.connect() as conn:
        return list(conn.execute(text("SELECT title FROM chunks ORDER BY title")).scalars())


def test_valid_webhook_updates_the_catalog(client: TestClient, admin_engine: Engine) -> None:
    assert post(client, "products/create", PAYLOAD) == 200
    assert titles(admin_engine) == ["Rain Jacket"]

    assert post(client, "products/delete", {"id": 42}) == 200
    assert titles(admin_engine) == []


def test_bad_signature_is_rejected(client: TestClient, admin_engine: Engine) -> None:
    assert post(client, "products/create", PAYLOAD, secret="wrong") == 401
    assert titles(admin_engine) == []


def test_unrelated_topics_are_ignored(client: TestClient, admin_engine: Engine) -> None:
    assert post(client, "orders/create", {"id": 1}) == 200
    assert titles(admin_engine) == []
