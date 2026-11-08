import uuid
from collections.abc import Iterator, Sequence
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.connectors.shopify.client import PolicyDoc, ProductDoc
from app.db import tenant_connection
from app.ingest.sync import embed_missing, sync_store, upsert_policy, upsert_product
from app.rag.embedder import EmbeddingError, HashingEmbedder, InputType

pytestmark = pytest.mark.usefixtures("clean_catalog")

SHOP = "demo.myshopify.com"


class CountingEmbedder(HashingEmbedder):
    def __init__(self, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    def embed(self, texts: Sequence[str], *, input_type: InputType) -> list[list[float]]:
        self.calls += 1
        if self.fail:
            raise EmbeddingError("down")
        return super().embed(texts, input_type=input_type)


def product(n: int, description: str = "Soft cotton tee.") -> ProductDoc:
    return ProductDoc(
        external_id=f"gid://shopify/Product/{n}",
        title=f"Tee {n}",
        description_html=f"<p>{description}</p>",
        handle=f"tee-{n}",
        price_min=Decimal("20.00"),
        price_max=Decimal("20.00"),
        available=True,
    )


def chunk_rows(engine: Engine, tenant: uuid.UUID) -> list[tuple[str, bool]]:
    with tenant_connection(engine, tenant) as conn:
        rows = conn.execute(text("SELECT content, embedding IS NOT NULL FROM chunks")).all()
    return [(row[0], row[1]) for row in rows]


def test_unchanged_content_is_not_re_embedded(
    app_engine: Engine, tenants: tuple[uuid.UUID, uuid.UUID]
) -> None:
    tenant = tenants[0]
    embedder = CountingEmbedder()

    with tenant_connection(app_engine, tenant) as conn:
        assert upsert_product(conn, tenant, SHOP, product(1), embedder) is True
    with tenant_connection(app_engine, tenant) as conn:
        assert upsert_product(conn, tenant, SHOP, product(1), embedder) is False

    assert embedder.calls == 1
    assert [embedded for _, embedded in chunk_rows(app_engine, tenant)] == [True]


def test_changed_content_replaces_its_chunks(
    app_engine: Engine, tenants: tuple[uuid.UUID, uuid.UUID]
) -> None:
    tenant = tenants[0]
    embedder = CountingEmbedder()
    with tenant_connection(app_engine, tenant) as conn:
        upsert_product(conn, tenant, SHOP, product(1), embedder)
        upsert_product(conn, tenant, SHOP, product(1, "Heavyweight organic cotton."), embedder)

    contents = [content for content, _ in chunk_rows(app_engine, tenant)]
    assert len(contents) == 1
    assert "Heavyweight organic cotton." in contents[0]


def test_embedding_outage_keeps_text_and_fills_vectors_later(
    app_engine: Engine, tenants: tuple[uuid.UUID, uuid.UUID]
) -> None:
    tenant = tenants[0]
    with tenant_connection(app_engine, tenant) as conn:
        upsert_product(conn, tenant, SHOP, product(1), CountingEmbedder(fail=True))
    assert [embedded for _, embedded in chunk_rows(app_engine, tenant)] == [False]

    with tenant_connection(app_engine, tenant) as conn:
        assert embed_missing(conn, HashingEmbedder()) == 1

    assert [embedded for _, embedded in chunk_rows(app_engine, tenant)] == [True]


def test_policies_are_chunked_with_their_url(
    app_engine: Engine, tenants: tuple[uuid.UUID, uuid.UUID]
) -> None:
    tenant = tenants[0]
    policy = PolicyDoc(
        kind="REFUND_POLICY",
        title="Refund policy",
        body_html="<p>Returns accepted within 30 days.</p>",
        url="https://demo.myshopify.com/policies/refund-policy",
    )
    with tenant_connection(app_engine, tenant) as conn:
        assert upsert_policy(conn, tenant, policy, HashingEmbedder()) is True
        assert upsert_policy(conn, tenant, policy, HashingEmbedder()) is False
        url = conn.execute(text("SELECT url FROM chunks WHERE source_type = 'policy'")).scalar()

    assert url == policy.url


class FakeClient:
    def __init__(self, products: list[ProductDoc]) -> None:
        self.products = products

    def iter_products(self) -> Iterator[ProductDoc]:
        yield from self.products

    def list_policies(self) -> list[PolicyDoc]:
        return []


def test_full_sync_removes_products_gone_from_the_store(
    app_engine: Engine, tenants: tuple[uuid.UUID, uuid.UUID]
) -> None:
    tenant = tenants[0]
    first = sync_store(
        app_engine, tenant, SHOP, FakeClient([product(1), product(2)]), HashingEmbedder()
    )
    second = sync_store(app_engine, tenant, SHOP, FakeClient([product(2)]), HashingEmbedder())

    assert (first.products_changed, second.products_changed, second.products_removed) == (2, 0, 1)
    contents = [content for content, _ in chunk_rows(app_engine, tenant)]
    assert len(contents) == 1
    assert contents[0].startswith("Tee 2")
