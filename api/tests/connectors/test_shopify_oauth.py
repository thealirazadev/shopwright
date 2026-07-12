import hashlib
import hmac

import httpx
import pytest

from app.connectors.shopify import oauth

SECRET = "test-api-secret"
SHOP = "demo-store.myshopify.com"


def signed_params(params: dict[str, str], secret: str = SECRET) -> dict[str, str]:
    message = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    digest = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    return {**params, "hmac": digest}


class TestShopDomain:
    @pytest.mark.parametrize(
        "shop", ["demo.myshopify.com", "a-1.myshopify.com", "0store.myshopify.com"]
    )
    def test_accepts_myshopify_domains(self, shop: str) -> None:
        assert oauth.valid_shop_domain(shop)

    @pytest.mark.parametrize(
        "shop",
        [
            "demo.example.com",
            "demo.myshopify.com.evil.com",
            "https://demo.myshopify.com",
            "UPPER.myshopify.com",
            "",
        ],
    )
    def test_rejects_everything_else(self, shop: str) -> None:
        assert not oauth.valid_shop_domain(shop)


class TestCallbackHmac:
    def test_valid_signature_passes(self) -> None:
        params = signed_params({"shop": SHOP, "code": "abc", "timestamp": "1700000000"})
        assert oauth.verify_authorize_callback(params, SECRET)

    def test_tampered_parameter_fails(self) -> None:
        params = signed_params({"shop": SHOP, "code": "abc", "timestamp": "1700000000"})
        params["shop"] = "attacker.myshopify.com"
        assert not oauth.verify_authorize_callback(params, SECRET)

    def test_missing_hmac_fails(self) -> None:
        assert not oauth.verify_authorize_callback({"shop": SHOP, "code": "abc"}, SECRET)


class TestState:
    def test_round_trip(self) -> None:
        state = oauth.sign_state(SHOP, SECRET, now=1_700_000_000)
        assert oauth.verify_state(state, SHOP, SECRET, now=1_700_000_100)

    def test_expired_state_fails(self) -> None:
        state = oauth.sign_state(SHOP, SECRET, now=1_700_000_000)
        assert not oauth.verify_state(state, SHOP, SECRET, now=1_700_001_000)

    def test_state_is_bound_to_shop(self) -> None:
        state = oauth.sign_state(SHOP, SECRET, now=1_700_000_000)
        assert not oauth.verify_state(state, "other.myshopify.com", SECRET, now=1_700_000_100)

    @pytest.mark.parametrize("state", ["", "garbage", "notanint.abc"])
    def test_malformed_state_fails(self, state: str) -> None:
        assert not oauth.verify_state(state, SHOP, SECRET, now=1_700_000_100)


class TestExchangeCode:
    def test_returns_access_token(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url == f"https://{SHOP}{oauth.ACCESS_TOKEN_PATH}"
            return httpx.Response(200, json={"access_token": "shpat_xyz", "scope": "read_products"})

        token = oauth.exchange_code(
            SHOP, "code", "key", SECRET, transport=httpx.MockTransport(handler)
        )
        assert token == "shpat_xyz"

    def test_error_response_raises(self) -> None:
        transport = httpx.MockTransport(lambda _: httpx.Response(401, json={}))
        with pytest.raises(httpx.HTTPStatusError):
            oauth.exchange_code(SHOP, "bad-code", "key", SECRET, transport=transport)

    def test_missing_token_in_response_raises(self) -> None:
        transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"scope": ""}))
        with pytest.raises(ValueError, match="no access token"):
            oauth.exchange_code(SHOP, "code", "key", SECRET, transport=transport)
