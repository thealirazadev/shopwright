import uuid

from sqlalchemy import Engine, text

from app.crypto import TokenCipher


def complete_install(
    engine: Engine, cipher: TokenCipher, *, shop: str, access_token: str, scopes: str
) -> uuid.UUID:
    """Persist a completed install: new tenant + store, or refreshed token on reinstall."""
    ciphertext = cipher.encrypt(access_token)
    with engine.begin() as conn:
        existing = conn.execute(
            text("SELECT tenant_id FROM stores WHERE shop_domain = :shop"), {"shop": shop}
        ).first()
        if existing is not None:
            tenant_id: uuid.UUID = existing[0]
            conn.execute(
                text(
                    """
                    UPDATE stores
                    SET access_token = :token, scopes = :scopes, updated_at = now()
                    WHERE shop_domain = :shop
                    """
                ),
                {"token": ciphertext, "scopes": scopes, "shop": shop},
            )
            return tenant_id

        tenant_id = conn.execute(
            text("INSERT INTO tenants (name, platform) VALUES (:name, 'shopify') RETURNING id"),
            {"name": shop},
        ).scalar_one()
        conn.execute(
            text(
                """
                INSERT INTO stores (tenant_id, shop_domain, access_token, scopes)
                VALUES (:tenant_id, :shop, :token, :scopes)
                """
            ),
            {"tenant_id": tenant_id, "shop": shop, "token": ciphertext, "scopes": scopes},
        )
        return tenant_id
