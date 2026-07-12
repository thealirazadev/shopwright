from cryptography.fernet import Fernet
from sqlalchemy import Engine, text

from app.connectors.shopify.service import complete_install
from app.crypto import TokenCipher


def test_install_creates_tenant_and_encrypted_store(admin_engine: Engine) -> None:
    shop = "install-test.myshopify.com"
    cipher = TokenCipher(Fernet.generate_key().decode())
    tenant_id = complete_install(
        admin_engine, cipher, shop=shop, access_token="shpat_first", scopes="read_products"
    )

    with admin_engine.connect() as conn:
        row = conn.execute(
            text("SELECT tenant_id, access_token FROM stores WHERE shop_domain = :s"),
            {"s": shop},
        ).one()
    assert row[0] == tenant_id
    stored: bytes = row[1]
    assert b"shpat_first" not in stored  # never plaintext at rest
    assert cipher.decrypt(stored) == "shpat_first"


def test_reinstall_rotates_token_without_duplicating(admin_engine: Engine) -> None:
    shop = "reinstall-test.myshopify.com"
    cipher = TokenCipher(Fernet.generate_key().decode())
    first = complete_install(
        admin_engine, cipher, shop=shop, access_token="shpat_first", scopes="read_products"
    )
    second = complete_install(
        admin_engine, cipher, shop=shop, access_token="shpat_second", scopes="read_products"
    )
    assert first == second

    with admin_engine.connect() as conn:
        count = conn.execute(
            text("SELECT count(*) FROM stores WHERE shop_domain = :s"), {"s": shop}
        ).scalar_one()
        token = conn.execute(
            text("SELECT access_token FROM stores WHERE shop_domain = :s"), {"s": shop}
        ).scalar_one()
    assert count == 1
    assert cipher.decrypt(token) == "shpat_second"
