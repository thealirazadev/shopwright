import json
from decimal import Decimal

import httpx
import pytest

from app.connectors.shopify.client import ProductDoc, ShopifyError, ShopifyReadClient


def product_node(n: int) -> dict[str, object]:
    return {
        "id": f"gid://shopify/Product/{n}",
        "title": f"Product {n}",
        "handle": f"product-{n}",
        "descriptionHtml": "<p>Nice</p>",
        "status": "ACTIVE",
        "tracksInventory": True,
        "totalInventory": n,
        "priceRangeV2": {
            "minVariantPrice": {"amount": "10.0"},
            "maxVariantPrice": {"amount": "12.5"},
        },
    }


def page(nodes: list[dict[str, object]], next_cursor: str | None) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "data": {
                "products": {
                    "pageInfo": {"hasNextPage": next_cursor is not None, "endCursor": next_cursor},
                    "nodes": nodes,
                }
            }
        },
    )


def client_with(handler: httpx.MockTransport) -> ShopifyReadClient:
    return ShopifyReadClient(
        "demo.myshopify.com",
        "shpat_test",
        http=httpx.Client(transport=handler),
        sleep=lambda _: None,
    )


def test_products_are_paginated_and_mapped() -> None:
    cursors: list[object] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Shopify-Access-Token"] == "shpat_test"
        cursor = json.loads(request.content)["variables"]["cursor"]
        cursors.append(cursor)
        return page([product_node(1)], "c1") if cursor is None else page([product_node(0)], None)

    products = list(client_with(httpx.MockTransport(handler)).iter_products())

    assert cursors == [None, "c1"]
    assert [p.external_id for p in products] == [
        "gid://shopify/Product/1",
        "gid://shopify/Product/0",
    ]
    assert products[0].price_min == Decimal("10.0")
    assert products[0].available is True
    assert products[1].available is False  # tracked inventory at zero


def test_throttling_and_server_errors_are_retried() -> None:
    responses = iter(
        [
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(200, json={"errors": [{"extensions": {"code": "THROTTLED"}}]}),
            httpx.Response(503),
            page([product_node(2)], None),
        ]
    )

    products = list(
        client_with(httpx.MockTransport(lambda request: next(responses))).iter_products()
    )

    assert [p.title for p in products] == ["Product 2"]


def test_graphql_errors_are_raised() -> None:
    handler = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"errors": [{"message": "Access denied"}]})
    )

    with pytest.raises(ShopifyError, match="Access denied"):
        list(client_with(handler).iter_products())


def test_retries_give_up() -> None:
    handler = httpx.MockTransport(lambda request: httpx.Response(503))

    with pytest.raises(ShopifyError):
        list(client_with(handler).iter_products())


def test_webhook_payload_maps_to_the_same_ids_as_graphql() -> None:
    doc = ProductDoc.from_webhook(
        {
            "id": 7,
            "admin_graphql_api_id": "gid://shopify/Product/7",
            "title": "Linen Shirt",
            "body_html": "<p>Breathable</p>",
            "handle": "linen-shirt",
            "status": "active",
            "variants": [
                {"price": "40.00", "inventory_management": "shopify", "inventory_quantity": 0},
                {"price": "45.00", "inventory_management": "shopify", "inventory_quantity": 3},
            ],
        }
    )

    assert doc.external_id == "gid://shopify/Product/7"
    assert (doc.price_min, doc.price_max) == (Decimal("40.00"), Decimal("45.00"))
    assert doc.available is True
