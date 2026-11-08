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


def issue(
    tenant_id: uuid.UUID,
    secret: str,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    role: str = "widget",
) -> str:
    claims = {"t": str(tenant_id), "exp": int(time.time()) + ttl_seconds, "r": role}
    payload = _b64(json.dumps(claims).encode())
    signature = _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{signature}"


def verify(token: str, secret: str, role: str = "widget") -> uuid.UUID:
    """Return the token's tenant id if it is valid for ``role``, or raise TokenError."""
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
        token_role = data.get("r", "widget")
    except (ValueError, KeyError, TypeError) as exc:
        raise TokenError("malformed token") from exc
    if token_role != role:
        raise TokenError("token is not valid for this API")
    if expires < time.time():
        raise TokenError("token expired")
    return tenant_id
