# Project Memory - Shopwright

Running log of what is done, in progress, and decided. Keep entries short and dated.

## Completed

- 2026-07-12 - Phase 0: FastAPI scaffold, tenant/product/store schema with forced RLS and an
  isolation test, Shopify OAuth with encrypted tokens, dashboard scaffold, CI.
- 2026-11-08 - Planning docs added: PRD, architecture, phases, rules, testing.
- 2026-11-08 - Phase 1: read-only Shopify GraphQL client with retries, policies and chunks tables
  with forced RLS, pgvector HNSW and full-text indexes, Voyage and hashing embedders, product and
  policy sync that re-embeds only changed content, HMAC-verified product webhooks, and hybrid
  retrieval with reciprocal rank fusion. 48 tests pass. Not yet run against a real store.
- 2026-11-08 - Phase 2, first part: Claude model client, catalog/product/policy/handoff tools,
  bounded loop (6 model calls, 12 tool calls) with citation filtering, and the eval harness with a
  demo store and 30 scenarios (8 safety). Recordings need one live run with ANTHROPIC_API_KEY.
  Remaining: conversations, messages, traces tables and the SSE chat endpoint.

## Open owner decisions

- Shopify development store for the demo and the live eval run.

## Decisions log

- 2026-11-08 - Refunds, returns, and cancellations are proposals approved by a merchant, never
  agent actions. The safety case for a support agent rests on this, and it is enforced by module
  boundaries and a test, not only the prompt.
- 2026-11-08 - Order access requires order number plus email, checked in the tool layer, with the
  same response for "no such order" and "wrong email" so the agent cannot be used to probe orders.
- 2026-11-08 - Single agent loop, no framework. Multi-agent designs add failure modes this
  product does not need; revisit only if evals show a gain.
- 2026-11-08 - Evals are built in phase 2, alongside the first tools, so every later behavior
  lands with scenarios.
- 2026-11-08 - Embeddings: Voyage AI, called over httpx (already a dependency) behind the
  `Embedder` interface, so no provider SDK is added. Anthropic has no embedding API, and Voyage is
  the provider Anthropic documents. Tests use a deterministic fake.
- 2026-11-08 - Agent model: `claude-sonnet-5-5`, set in config.
- 2026-11-08 - Full sync uses paginated GraphQL, not bulk operations: simpler, and fine for the
  catalog sizes in ADR-002. Revisit for stores above roughly 10k products.
- 2026-11-08 - Webhooks are applied inline rather than through the Redis queue; one product per
  call is small. Move to the queue if webhook latency or volume requires it.
- 2026-11-08 - A failed embedding call stores chunks with a NULL vector instead of failing the
  sync; text search still finds them and `embed_missing` fills them later.
- 2026-11-08 - Full-text search matches any query word (OR), because shoppers' questions rarely
  contain every word of the answer; vector ranking and rank fusion handle precision.
- 2026-11-08 - Evals use the hashing embedder so a recorded run replays byte for byte in CI;
  retrieval quality has its own tests. Replay only exercises the agent's decisions against a
  fixed store, which is what the scenarios assert.
