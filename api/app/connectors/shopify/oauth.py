"""Shopify OAuth primitives: callback HMAC verification, CSRF state, token exchange.

Reference: https://shopify.dev/docs/apps/build/authentication-authorization/access-tokens/authorization-code-grant
"""

import hashlib
import hmac
import re
import time
from collections.abc import Mapping
from urllib.parse import urlencode

import httpx

AUTHORIZE_PATH = "/admin/oauth/authorize"
ACCESS_TOKEN_PATH = "/admin/oauth/access_token"

_SHOP_DOMAIN_RE = re.compile(r"^[a-z0-9][a-z0-9-]*\.myshopify\.com$")
_STATE_TTL_SECONDS = 600
_EXCHANGE_TIMEOUT_SECONDS = 10.0


def valid_shop_domain(shop: str) -> bool:
    return _SHOP_DOMAIN_RE.fullmatch(shop) is not None


def verify_authorize_callback(params: Mapping[str, str], api_secret: str) -> bool:
    """Verify the ``hmac`` query parameter Shopify appends to OAuth redirects.

    Signature covers all query parameters except ``hmac`` itself (and the
    legacy ``signature``), sorted by key, as SHA-256 HMAC of the app secret.
    """
    received = params.get("hmac", "")
    if not received:
        return False
    message = "&".join(
        f"{key}={value}"
        for key, value in sorted(params.items())
        if key not in ("hmac", "signature")
    )
    expected = hmac.new(api_secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, received)


def sign_state(shop: str, api_secret: str, *, now: float | None = None) -> str:
    """CSRF token binding the OAuth round-trip to one shop, no server storage."""
    issued = int(now if now is not None else time.time())
    signature = _state_signature(shop, issued, api_secret)
    return f"{issued}.{signature}"


def verify_state(state: str, shop: str, api_secret: str, *, now: float | None = None) -> bool:
    issued_raw, _, signature = state.partition(".")
    try:
        issued = int(issued_raw)
    except ValueError:
        return False
    current = now if now is not None else time.time()
    if not (0 <= current - issued <= _STATE_TTL_SECONDS):
        return False
    expected = _state_signature(shop, issued, api_secret)
    return hmac.compare_digest(expected, signature)


def _state_signature(shop: str, issued: int, api_secret: str) -> str:
    payload = f"state:{shop}:{issued}"
    return hmac.new(api_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def build_authorize_url(shop: str, api_key: str, scopes: str, redirect_uri: str, state: str) -> str:
    query = urlencode(
        {"client_id": api_key, "scope": scopes, "redirect_uri": redirect_uri, "state": state}
    )
    return f"https://{shop}{AUTHORIZE_PATH}?{query}"


def exchange_code(
    shop: str,
    code: str,
    api_key: str,
    api_secret: str,
    transport: httpx.BaseTransport | None = None,
) -> str:
    """Trade the authorization code for a permanent access token."""
    with httpx.Client(timeout=_EXCHANGE_TIMEOUT_SECONDS, transport=transport) as client:
        response = client.post(
            f"https://{shop}{ACCESS_TOKEN_PATH}",
            json={"client_id": api_key, "client_secret": api_secret, "code": code},
        )
        response.raise_for_status()
        token = response.json().get("access_token")
    if not isinstance(token, str) or not token:
        raise ValueError("Shopify token exchange returned no access token")
    return token
