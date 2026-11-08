"""Hybrid retrieval: vector similarity plus full-text rank, merged with reciprocal rank fusion.

The caller passes a tenant-scoped connection, so RLS limits every query to one store.
"""

import logging
import re
import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, text

from app.rag.embedder import Embedder, EmbeddingError, to_pgvector

logger = logging.getLogger(__name__)

RRF_K = 60
CANDIDATES = 20


@dataclass(frozen=True)
class Hit:
    chunk_id: uuid.UUID
    source_type: str
    source_id: uuid.UUID
    title: str
    url: str | None
    content: str
    score: float


def _or_query(query: str) -> str:
    """Any-word match: a shopper's question rarely contains every word of the answer."""
    return " | ".join(re.findall(r"[a-z0-9]+", query.lower()))


def search(
    conn: Connection,
    query: str,
    embedder: Embedder,
    *,
    limit: int = 5,
    source_type: str | None = None,
) -> list[Hit]:
    type_filter = "AND source_type = :type" if source_type else ""
    params: dict[str, object] = {"type": source_type, "k": CANDIDATES}
    rankings: list[list[uuid.UUID]] = []

    try:
        vector = embedder.embed([query], input_type="query")[0]
    except EmbeddingError:
        logger.warning("retrieval.vector_skipped")
    else:
        rankings.append(
            list(
                conn.execute(
                    text(
                        f"""
                        SELECT id FROM chunks
                        WHERE embedding IS NOT NULL {type_filter}
                        ORDER BY embedding <=> CAST(:vector AS vector)
                        LIMIT :k
                        """
                    ),
                    {**params, "vector": to_pgvector(vector)},
                ).scalars()
            )
        )

    terms = _or_query(query)
    if terms:
        rankings.append(
            list(
                conn.execute(
                    text(
                        f"""
                        SELECT id FROM chunks
                        WHERE tsv @@ to_tsquery('english', :terms) {type_filter}
                        ORDER BY ts_rank(tsv, to_tsquery('english', :terms)) DESC
                        LIMIT :k
                        """
                    ),
                    {**params, "terms": terms},
                ).scalars()
            )
        )

    scores: dict[uuid.UUID, float] = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank + 1)
    top = sorted(scores, key=lambda chunk_id: scores[chunk_id], reverse=True)[:limit]
    if not top:
        return []

    rows = {
        row.id: row
        for row in conn.execute(
            text(
                "SELECT id, source_type, source_id, title, url, content FROM chunks "
                "WHERE id = ANY(:ids)"
            ),
            {"ids": top},
        )
    }
    return [
        Hit(
            chunk_id=chunk_id,
            source_type=rows[chunk_id].source_type,
            source_id=rows[chunk_id].source_id,
            title=rows[chunk_id].title,
            url=rows[chunk_id].url,
            content=rows[chunk_id].content,
            score=scores[chunk_id],
        )
        for chunk_id in top
        if chunk_id in rows
    ]
