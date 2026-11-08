import hashlib
import hmac
from collections.abc import Iterator
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.config import get_settings
from app.connectors.shopify import oauth
from app.main import app

SECRET = "route-test-secret"
SHOP = "route-test.myshopify.com"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, admin_engine: Engine) -> Iterator[TestClient]:
    monkeypatch.setenv("SHOPIFY_API_KEY", "key123")
    monkeypatch.setenv("SHOPIFY_API_SECRET", SECRET)
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr("app.connectors.shopify.router.get_engine", lambda: admin_engine)
    get_settings.cache_clear()
    yield TestClient(app, follow_redirects=False)
    get_settings.cache_clear()


def signed(params: dict[str, str]) -> dict[str, str]:
    message = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    digest = hmac.new(SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()
    return {**params, "hmac": digest}


def callback_params(**overrides: str) -> dict[str, str]:
    params = {"shop": SHOP, "code": "abc", "state": oauth.sign_state(SHOP, SECRET)}
    params.update(overrides)
    return signed(params)


def test_install_redirects_to_shopify_with_signed_state(client: TestClient) -> None:
    response = client.get("/connect/shopify/install", params={"shop": SHOP})

    assert response.status_code == 307
    url = urlparse(response.headers["location"])
    query = parse_qs(url.query)
    assert url.netloc == SHOP
    assert query["client_id"] == ["key123"]
    assert oauth.verify_state(query["state"][0], SHOP, SECRET)


@pytest.mark.parametrize("shop", ["evil.com", "x.myshopify.com.evil.com", ""])
def test_install_rejects_shops_outside_myshopify(client: TestClient, shop: str) -> None:
    assert client.get("/connect/shopify/install", params={"shop": shop}).status_code == 422


def test_install_without_app_credentials_is_unavailable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SHOPIFY_API_SECRET", "")
    get_settings.cache_clear()
    assert client.get("/connect/shopify/install", params={"shop": SHOP}).status_code == 503


def test_callback_stores_the_exchanged_token_encrypted(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, admin_engine: Engine
) -> None:
    monkeypatch.setattr(oauth, "exchange_code", lambda *a: "shpat_route")
    response = client.get("/connect/shopify/callback", params=callback_params())

    assert response.status_code == 200
    assert response.json()["status"] == "connected"
    with admin_engine.connect() as conn:
        stored = conn.execute(
            text("SELECT access_token FROM stores WHERE shop_domain = :s"), {"s": SHOP}
        ).scalar_one()
    assert b"shpat_route" not in stored


@pytest.mark.parametrize(
    ("params", "status"),
    [
        ({**callback_params(), "hmac": "0" * 64}, 400),
        (callback_params(state="1.forged"), 400),
        (callback_params(state=oauth.sign_state(SHOP, SECRET, now=1)), 400),
        (callback_params(code=""), 400),
        (callback_params(shop="evil.com"), 422),
    ],
    ids=["bad-hmac", "forged-state", "expired-state", "no-code", "bad-shop"],
)
def test_callback_rejects_tampered_requests(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, params: dict[str, str], status: int
) -> None:
    def never(*args: str) -> str:
        raise AssertionError("token exchange must not run")

    monkeypatch.setattr(oauth, "exchange_code", never)
    assert client.get("/connect/shopify/callback", params=params).status_code == status


def test_a_failed_token_exchange_returns_a_friendly_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing(*args: str) -> str:
        raise httpx.ConnectError("down")

    monkeypatch.setattr(oauth, "exchange_code", failing)
    response = client.get("/connect/shopify/callback", params=callback_params())

    assert response.status_code == 502
    assert "try again" in response.json()["detail"]
