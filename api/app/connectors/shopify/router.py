from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.config import Settings, get_settings
from app.connectors.shopify import oauth
from app.connectors.shopify.service import complete_install
from app.crypto import get_cipher
from app.db import get_engine

router = APIRouter(prefix="/connect/shopify", tags=["connectors"])


def _require_credentials(settings: Settings) -> None:
    if not settings.shopify_api_key or not settings.shopify_api_secret:
        raise HTTPException(status_code=503, detail="Shopify credentials are not configured")


@router.get("/install")
def install(shop: str) -> RedirectResponse:
    settings = get_settings()
    _require_credentials(settings)
    if not oauth.valid_shop_domain(shop):
        raise HTTPException(status_code=422, detail="invalid shop domain")
    url = oauth.build_authorize_url(
        shop=shop,
        api_key=settings.shopify_api_key,
        scopes=settings.shopify_scopes,
        redirect_uri=f"{settings.app_url}/connect/shopify/callback",
        state=oauth.sign_state(shop, settings.shopify_api_secret),
    )
    return RedirectResponse(url, status_code=307)


@router.get("/callback")
def callback(request: Request) -> dict[str, str]:
    settings = get_settings()
    _require_credentials(settings)
    params = dict(request.query_params)
    shop = params.get("shop", "")
    if not oauth.valid_shop_domain(shop):
        raise HTTPException(status_code=422, detail="invalid shop domain")
    if not oauth.verify_authorize_callback(params, settings.shopify_api_secret):
        raise HTTPException(status_code=400, detail="hmac verification failed")
    if not oauth.verify_state(params.get("state", ""), shop, settings.shopify_api_secret):
        raise HTTPException(status_code=400, detail="state expired or invalid")
    code = params.get("code", "")
    if not code:
        raise HTTPException(status_code=400, detail="missing authorization code")

    access_token = oauth.exchange_code(
        shop, code, settings.shopify_api_key, settings.shopify_api_secret
    )
    tenant_id = complete_install(
        get_engine(),
        get_cipher(),
        shop=shop,
        access_token=access_token,
        scopes=settings.shopify_scopes,
    )
    return {"status": "connected", "shop": shop, "tenant_id": str(tenant_id)}
