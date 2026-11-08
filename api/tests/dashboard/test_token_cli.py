import uuid

import pytest
from sqlalchemy import Engine, text

from app.chat import tokens
from app.config import get_settings
from app.dashboard.token import main


def test_issues_a_merchant_token_for_an_installed_store(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    admin_engine: Engine,
    tenants: tuple[uuid.UUID, uuid.UUID],
) -> None:
    monkeypatch.setenv("WIDGET_TOKEN_SECRET", "cli-secret")
    get_settings.cache_clear()
    with admin_engine.begin() as conn:
        conn.execute(text("DELETE FROM stores WHERE shop_domain = 'cli-b.myshopify.com'"))
        conn.execute(
            text(
                "INSERT INTO stores (tenant_id, shop_domain, access_token) "
                "VALUES (:t, 'cli-b.myshopify.com', 'x')"
            ),
            {"t": tenants[1]},
        )

    assert main(["cli-b.myshopify.com"]) == 0
    token = capsys.readouterr().out.strip()
    assert tokens.verify(token, "cli-secret", role="merchant") == tenants[1]
    assert main(["missing.myshopify.com"]) == 1
    get_settings.cache_clear()
