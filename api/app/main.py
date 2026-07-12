from fastapi import FastAPI

from app.connectors.shopify.router import router as shopify_router

app = FastAPI(title="Shopwright API")
app.include_router(shopify_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
