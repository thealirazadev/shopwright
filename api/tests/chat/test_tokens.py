import uuid

import pytest

from app.chat import tokens

SECRET = "token-secret"
TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")


def test_round_trip() -> None:
    assert tokens.verify(tokens.issue(TENANT, SECRET), SECRET) == TENANT


@pytest.mark.parametrize(
    "token",
    [
        "garbage",
        tokens.issue(TENANT, "other-secret"),
        tokens.issue(TENANT, SECRET, ttl_seconds=-1),
        tokens.issue(TENANT, SECRET)[:-2] + "xx",
    ],
    ids=["malformed", "wrong-secret", "expired", "tampered"],
)
def test_rejected_tokens(token: str) -> None:
    with pytest.raises(tokens.TokenError):
        tokens.verify(token, SECRET)


def test_an_unconfigured_secret_rejects_everything() -> None:
    with pytest.raises(tokens.TokenError):
        tokens.verify(tokens.issue(TENANT, ""), "")
