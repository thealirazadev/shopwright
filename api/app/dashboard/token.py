"""Issue a merchant dashboard token for an installed store.

    uv run python -m app.dashboard.token your-store.myshopify.com

Until the dashboard is embedded in Shopify admin (which would use Shopify session tokens),
this is how a merchant signs in: the operator issues a token and the merchant pastes it.
"""

import sys
from collections.abc import Sequence

from sqlalchemy import text

from app.chat import tokens
from app.config import get_settings
from app.db import get_engine

MERCHANT_TTL_SECONDS = 8 * 3600


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: python -m app.dashboard.token <shop-domain>", file=sys.stderr)
        return 2
    secret = get_settings().widget_token_secret
    if not secret:
        print("error: WIDGET_TOKEN_SECRET is not set", file=sys.stderr)
        return 2
    with get_engine().connect() as conn:
        tenant_id = conn.execute(
            text("SELECT tenant_id FROM stores WHERE shop_domain = :shop"), {"shop": args[0]}
        ).scalar()
    if tenant_id is None:
        print(f"error: {args[0]} is not installed", file=sys.stderr)
        return 1
    print(tokens.issue(tenant_id, secret, ttl_seconds=MERCHANT_TTL_SECONDS, role="merchant"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
