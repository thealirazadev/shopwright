import httpx
import pytest

from app.connectors.shopify.client import ShopifyError
from app.connectors.shopify.write import ShopifyWriteClient


def writer(errors: list[dict[str, str]]) -> ShopifyWriteClient:
    response = {"data": {"orderCancel": {"userErrors": errors}}}
    return ShopifyWriteClient(
        "demo.myshopify.com",
        "shpat_test",
        http=httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=response))
        ),
        sleep=lambda _: None,
    )


def test_a_cancellation_shopify_accepts_returns_quietly() -> None:
    writer([]).cancel_order("gid://shopify/Order/1")


def test_a_cancellation_shopify_refuses_raises_its_message() -> None:
    with pytest.raises(ShopifyError, match="already cancelled"):
        writer([{"field": "orderId", "message": "already cancelled"}]).cancel_order("gid://1")
