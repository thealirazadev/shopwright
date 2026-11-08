"""Keep products, policies, and their chunks in step with the store.

A source is re-chunked and re-embedded only when its content hash changes. If
the embedding call fails, chunks are stored with a NULL embedding so text
search still works, and embed_missing fills them in later.
"""

import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import Connection, Engine, text

from app.connectors.shopify.client import PolicyDoc, ProductDoc
from app.db import tenant_connection
from app.ingest.chunking import content_hash, html_to_text, product_text, split_text
from app.rag.embedder import Embedder, EmbeddingError, to_pgvector

logger = logging.getLogger(__name__)


class CatalogSource(Protocol):
    def iter_products(self) -> Iterable[ProductDoc]: ...

    def list_policies(self) -> list[PolicyDoc]: ...


@dataclass
class SyncStats:
    products_changed: int = 0
    products_removed: int = 0
    policies_changed: int = 0


def _replace_chunks(
    conn: Connection,
    tenant_id: uuid.UUID,
    source_type: str,
    source_id: uuid.UUID,
    title: str,
    url: str | None,
    body: str,
    embedder: Embedder,
) -> None:
    conn.execute(
        text("DELETE FROM chunks WHERE source_type = :type AND source_id = :id"),
        {"type": source_type, "id": source_id},
    )
    pieces = split_text(body)
    vectors: list[str | None]
    try:
        vectors = [to_pgvector(v) for v in embedder.embed(pieces, input_type="document")]
    except EmbeddingError:
        logger.warning("ingest.embedding_deferred", extra={"source_id": str(source_id)})
        vectors = [None] * len(pieces)
    for position, (piece, vector) in enumerate(zip(pieces, vectors, strict=True)):
        conn.execute(
            text(
                """
                INSERT INTO chunks
                    (tenant_id, source_type, source_id, position, title, url, content, embedding)
                VALUES (:tenant, :type, :source, :pos, :title, :url, :content,
                        CAST(:embedding AS vector))
                """
            ),
            {
                "tenant": tenant_id,
                "type": source_type,
                "source": source_id,
                "pos": position,
                "title": title,
                "url": url,
                "content": piece,
                "embedding": vector,
            },
        )


def upsert_product(
    conn: Connection, tenant_id: uuid.UUID, shop: str, doc: ProductDoc, embedder: Embedder
) -> bool:
    """Store one product; return True when its searchable content changed."""
    body = product_text(doc)
    digest = content_hash(body)
    existing = conn.execute(
        text("SELECT id, content_hash FROM products WHERE external_id = :ext"),
        {"ext": doc.external_id},
    ).first()
    product_id: uuid.UUID = conn.execute(
        text(
            """
            INSERT INTO products (tenant_id, external_id, title, description, handle,
                                  price_min, price_max, available, content_hash)
            VALUES (:tenant, :ext, :title, :description, :handle,
                    :price_min, :price_max, :available, :hash)
            ON CONFLICT (tenant_id, external_id) DO UPDATE SET
                title = EXCLUDED.title, description = EXCLUDED.description,
                handle = EXCLUDED.handle, price_min = EXCLUDED.price_min,
                price_max = EXCLUDED.price_max, available = EXCLUDED.available,
                content_hash = EXCLUDED.content_hash, updated_at = now()
            RETURNING id
            """
        ),
        {
            "tenant": tenant_id,
            "ext": doc.external_id,
            "title": doc.title,
            "description": doc.description_html,
            "handle": doc.handle,
            "price_min": doc.price_min,
            "price_max": doc.price_max,
            "available": doc.available,
            "hash": digest,
        },
    ).scalar_one()
    if existing is not None and existing.content_hash == digest:
        return False
    url = f"https://{shop}/products/{doc.handle}" if doc.handle else None
    _replace_chunks(conn, tenant_id, "product", product_id, doc.title, url, body, embedder)
    return True


def delete_product(conn: Connection, external_id: str) -> None:
    product_id = conn.execute(
        text("DELETE FROM products WHERE external_id = :ext RETURNING id"), {"ext": external_id}
    ).scalar()
    if product_id is not None:
        conn.execute(
            text("DELETE FROM chunks WHERE source_type = 'product' AND source_id = :id"),
            {"id": product_id},
        )


def upsert_policy(
    conn: Connection, tenant_id: uuid.UUID, doc: PolicyDoc, embedder: Embedder
) -> bool:
    body = html_to_text(doc.body_html)
    digest = content_hash(f"{doc.title}\n{body}")
    existing = conn.execute(
        text("SELECT content_hash FROM policies WHERE kind = :kind"), {"kind": doc.kind}
    ).first()
    if existing is not None and existing.content_hash == digest:
        return False
    policy_id: uuid.UUID = conn.execute(
        text(
            """
            INSERT INTO policies (tenant_id, kind, title, body, url, content_hash)
            VALUES (:tenant, :kind, :title, :body, :url, :hash)
            ON CONFLICT (tenant_id, kind) DO UPDATE SET
                title = EXCLUDED.title, body = EXCLUDED.body, url = EXCLUDED.url,
                content_hash = EXCLUDED.content_hash, updated_at = now()
            RETURNING id
            """
        ),
        {
            "tenant": tenant_id,
            "kind": doc.kind,
            "title": doc.title,
            "body": body,
            "url": doc.url,
            "hash": digest,
        },
    ).scalar_one()
    _replace_chunks(conn, tenant_id, "policy", policy_id, doc.title, doc.url, body, embedder)
    return True


def sync_store(
    engine: Engine,
    tenant_id: uuid.UUID,
    shop: str,
    client: CatalogSource,
    embedder: Embedder,
) -> SyncStats:
    """Full sync. Each product commits on its own so one bad item cannot undo the rest."""
    stats = SyncStats()
    seen: set[str] = set()
    for doc in client.iter_products():
        seen.add(doc.external_id)
        with tenant_connection(engine, tenant_id) as conn:
            stats.products_changed += upsert_product(conn, tenant_id, shop, doc, embedder)

    with tenant_connection(engine, tenant_id) as conn:
        stored = conn.execute(text("SELECT external_id FROM products")).scalars().all()
        for external_id in set(stored) - seen:
            delete_product(conn, external_id)
            stats.products_removed += 1

    for policy in client.list_policies():
        with tenant_connection(engine, tenant_id) as conn:
            stats.policies_changed += upsert_policy(conn, tenant_id, policy, embedder)
    return stats


def embed_missing(conn: Connection, embedder: Embedder, limit: int = 256) -> int:
    """Embed chunks stored without a vector. Returns how many were filled."""
    rows = conn.execute(
        text("SELECT id, content FROM chunks WHERE embedding IS NULL LIMIT :limit"),
        {"limit": limit},
    ).all()
    if not rows:
        return 0
    vectors = embedder.embed([row.content for row in rows], input_type="document")
    for row, vector in zip(rows, vectors, strict=True):
        conn.execute(
            text("UPDATE chunks SET embedding = CAST(:v AS vector) WHERE id = :id"),
            {"v": to_pgvector(vector), "id": row.id},
        )
    return len(rows)
