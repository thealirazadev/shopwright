"""Read-only Shopify Admin GraphQL client.

Only reads live here. Writes (refunds, cancellations) belong to a separate
client that the agent package is not allowed to import.
"""

import logging
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import httpx

logger = logging.getLogger(__name__)

API_VERSION = "2025-10"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}

PRODUCTS_QUERY = """
query Products($cursor: String) {
  products(first: 50, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id title handle descriptionHtml status tracksInventory totalInventory
      priceRangeV2 { minVariantPrice { amount } maxVariantPrice { amount } }
    }
  }
}
"""

POLICIES_QUERY = "query { shop { shopPolicies { type title body url } } }"


class ShopifyError(Exception):
    pass


@dataclass(frozen=True)
class ProductDoc:
    external_id: str
    title: str
    description_html: str
    handle: str
    price_min: Decimal | None
    price_max: Decimal | None
    available: bool

    @classmethod
    def from_graphql(cls, node: dict[str, Any]) -> "ProductDoc":
        prices = node.get("priceRangeV2") or {}
        in_stock = not node.get("tracksInventory") or (node.get("totalInventory") or 0) > 0
        return cls(
            external_id=node["id"],
            title=node["title"],
            description_html=node.get("descriptionHtml") or "",
            handle=node.get("handle") or "",
            price_min=_amount(prices.get("minVariantPrice")),
            price_max=_amount(prices.get("maxVariantPrice")),
            available=node.get("status") == "ACTIVE" and in_stock,
        )

    @classmethod
    def from_webhook(cls, payload: dict[str, Any]) -> "ProductDoc":
        variants = payload.get("variants") or []
        prices = [Decimal(str(v["price"])) for v in variants if v.get("price") is not None]
        in_stock = any(
            v.get("inventory_management") is None or (v.get("inventory_quantity") or 0) > 0
            for v in variants
        )
        return cls(
            external_id=payload["admin_graphql_api_id"],
            title=payload["title"],
            description_html=payload.get("body_html") or "",
            handle=payload.get("handle") or "",
            price_min=min(prices) if prices else None,
            price_max=max(prices) if prices else None,
            available=payload.get("status") == "active" and in_stock,
        )


@dataclass(frozen=True)
class PolicyDoc:
    kind: str
    title: str
    body_html: str
    url: str | None


def _amount(money: dict[str, Any] | None) -> Decimal | None:
    if not money or money.get("amount") is None:
        return None
    return Decimal(str(money["amount"]))


class ShopifyReadClient:
    def __init__(
        self,
        shop: str,
        access_token: str,
        *,
        http: httpx.Client | None = None,
        max_retries: int = 4,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._url = f"https://{shop}/admin/api/{API_VERSION}/graphql.json"
        self._headers = {"X-Shopify-Access-Token": access_token}
        self._http = http or httpx.Client(timeout=20)
        self._max_retries = max_retries
        self._sleep = sleep

    def _query(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run one GraphQL query, retrying throttling, 5xx, and network errors with backoff."""
        for attempt in range(self._max_retries + 1):
            delay = 0.5 * 2**attempt
            try:
                response = self._http.post(
                    self._url,
                    headers=self._headers,
                    json={"query": query, "variables": variables or {}},
                )
            except httpx.TransportError as exc:
                logger.warning("shopify.transport_error", extra={"attempt": attempt})
                if attempt == self._max_retries:
                    raise ShopifyError("Shopify is unreachable") from exc
                self._sleep(delay)
                continue

            if response.status_code in RETRYABLE_STATUS and attempt < self._max_retries:
                retry_after = response.headers.get("Retry-After")
                self._sleep(float(retry_after) if retry_after else delay)
                continue
            if response.status_code != 200:
                raise ShopifyError(f"Shopify returned HTTP {response.status_code}")

            body: dict[str, Any] = response.json()
            errors = body.get("errors") or []
            throttled = any((e.get("extensions") or {}).get("code") == "THROTTLED" for e in errors)
            if throttled and attempt < self._max_retries:
                self._sleep(delay)
                continue
            if errors:
                raise ShopifyError(f"Shopify GraphQL error: {errors[0].get('message')}")
            data: dict[str, Any] = body["data"]
            return data
        raise ShopifyError("Shopify kept throttling the request")

    def iter_products(self) -> Iterator[ProductDoc]:
        cursor: str | None = None
        while True:
            page = self._query(PRODUCTS_QUERY, {"cursor": cursor})["products"]
            for node in page["nodes"]:
                yield ProductDoc.from_graphql(node)
            if not page["pageInfo"]["hasNextPage"]:
                return
            cursor = page["pageInfo"]["endCursor"]

    def list_policies(self) -> list[PolicyDoc]:
        policies = self._query(POLICIES_QUERY)["shop"]["shopPolicies"]
        return [
            PolicyDoc(
                kind=p["type"], title=p["title"], body_html=p.get("body") or "", url=p.get("url")
            )
            for p in policies
            if p.get("body")
        ]
