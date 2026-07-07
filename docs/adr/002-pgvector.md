# ADR-002: pgvector over a dedicated vector database

Status: accepted · Date: 2026-07-07

## Context

The RAG pipeline stores one embedding per content chunk (products, policies,
pages) per store. Candidates: a dedicated vector DB (Pinecone, Qdrant,
Weaviate) or pgvector inside the Postgres instance that already holds all
tenant data.

Realistic scale: a store with 5,000 products at ~4 chunks each is ~20k
vectors; even a hundred stores stays comfortably under a million. HNSW
indexes in pgvector handle this range well.

## Decision

pgvector in the primary Postgres database (Neon), with HNSW indexes.

The deciding factors, in order:

1. **Transactional consistency.** A product update and its re-embedding
   commit together or not at all. With an external store this becomes a
   distributed-consistency problem we'd have to paper over with reconciliation
   jobs.
2. **Tenant isolation for free.** Row-level security policies (ADR-003) apply
   to embeddings exactly as they do to the rest of the tenant's rows. A
   separate vector DB would need its own isolation story.
3. **One database to operate.** One backup, one connection pool, one thing to
   monitor — and no extra paid service.

## Consequences

- Vector search competes with transactional load on the same instance. Fine
  at this scale; worth watching once query volume grows.
- Revisit if any single deployment approaches ~5M embeddings or retrieval
  latency degrades measurably. Migration path is straightforward: chunks are
  keyed by stable IDs, so a dedicated store can be backfilled from Postgres
  and swapped in behind the retrieval interface.
