from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.actions.router import router as approvals_router
from app.chat.router import router as chat_router
from app.config import get_settings
from app.connectors.shopify.router import router as shopify_router
from app.dashboard.router import router as dashboard_router
from app.ingest.webhooks import router as webhook_router

app = FastAPI(title="Shopwright API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().cors_origins.split(",") if o.strip()],
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)
app.include_router(shopify_router)
app.include_router(webhook_router)
app.include_router(chat_router)
app.include_router(approvals_router)
app.include_router(dashboard_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
