from decimal import Decimal
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://shopwright:shopwright@localhost:5432/shopwright"
    redis_url: str = "redis://localhost:6379/0"

    app_url: str = "http://localhost:8000"

    shopify_api_key: str = ""
    shopify_api_secret: str = ""
    shopify_scopes: str = "read_products,read_content,read_orders,write_orders"

    # Fernet key encrypting store access tokens at rest (see .env.example).
    token_encryption_key: str = ""

    # Embeddings (Voyage AI). Without a key, a local hashing embedder is used.
    voyage_api_key: str = ""
    embedding_model: str = "voyage-3.5"

    anthropic_api_key: str = ""
    # Signs short-lived widget tokens that bind a chat session to one store.
    widget_token_secret: str = ""
    agent_model: str = "claude-sonnet-5-5"
    # USD per million tokens for the agent model, used by the dashboard's cost overview.
    # Set these from Anthropic's current pricing page; at 0 the dashboard shows tokens only.
    agent_input_usd_per_mtok: Decimal = Decimal("0")
    agent_output_usd_per_mtok: Decimal = Decimal("0")


@lru_cache
def get_settings() -> Settings:
    return Settings()
