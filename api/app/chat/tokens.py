"""Short-lived widget tokens: base64url(payload).base64url(hmac-sha256).

A token names exactly one store (tenant). The chat API takes the tenant from
the token and nowhere else, so a widget for store A cannot reach store B.
"""

import base64
import hashlib
import hmac
import json
import time
import uuid

DEFAULT_TTL_SECONDS = 3600


class TokenError(Exception):
    pass


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def issue(tenant_id: uuid.UUID, secret: str, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> str:
    payload = _b64(
        json.dumps({"t": str(tenant_id), "exp": int(time.time()) + ttl_seconds}).encode()
    )
    signature = _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{signature}"


def verify(token: str, secret: str) -> uuid.UUID:
    """Return the token's tenant id, or raise TokenError."""
    if not secret:
        raise TokenError("widget tokens are not configured")
    try:
        payload, signature = token.split(".")
    except ValueError as exc:
        raise TokenError("malformed token") from exc
    expected = _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(expected, signature):
        raise TokenError("bad signature")
    try:
        data = json.loads(_unb64(payload))
        tenant_id = uuid.UUID(data["t"])
        expires = int(data["exp"])
    except (ValueError, KeyError, TypeError) as exc:
        raise TokenError("malformed token") from exc
    if expires < time.time():
        raise TokenError("token expired")
    return tenant_id
