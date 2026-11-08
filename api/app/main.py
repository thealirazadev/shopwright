from fastapi import FastAPI

from app.chat.router import router as chat_router
from app.connectors.shopify.router import router as shopify_router
from app.ingest.webhooks import router as webhook_router

app = FastAPI(title="Shopwright API")
app.include_router(shopify_router)
app.include_router(webhook_router)
app.include_router(chat_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
