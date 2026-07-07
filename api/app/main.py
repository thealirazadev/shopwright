from fastapi import FastAPI

app = FastAPI(title="Shopwright API")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
