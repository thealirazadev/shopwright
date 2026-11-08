"""Shopify write calls. Imported only by app.actions, never by the agent.

A test (tests/agent/test_boundaries.py) fails if anything under app/agent
imports this module, so the agent cannot change an order even if prompted to.
"""

from typing import Any

from app.connectors.shopify.client import ShopifyError, ShopifyReadClient

CANCEL_MUTATION = """
mutation Cancel($orderId: ID!) {
  orderCancel(orderId: $orderId, reason: CUSTOMER, refund: true, restock: true,
              notifyCustomer: true) {
    userErrors { field message }
  }
}
"""


class ShopifyWriteClient(ShopifyReadClient):
    def cancel_order(self, order_id: str) -> None:
        data: dict[str, Any] = self._query(CANCEL_MUTATION, {"orderId": order_id})
        errors = data["orderCancel"]["userErrors"]
        if errors:
            raise ShopifyError(f"Shopify refused the cancellation: {errors[0]['message']}")
