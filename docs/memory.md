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
  Then: conversations, messages, and traces tables (forced RLS), signed per-store widget tokens,
  and `POST /v1/chat`, which resumes a conversation, runs the agent, and stores every message and
  trace. A handed-off conversation never calls the model again. 67 tests pass.
- 2026-11-08 - Phase 3: `verify_customer`, `get_order`, and `propose_action` tools; verified orders
  and attempt counts persist per conversation; `action_proposals` with forced RLS; merchant
  approvals API (`/v1/admin/proposals`) behind merchant-role tokens; a separate Shopify write
  client reachable only from `app.actions`, guarded by an import-boundary test. Eval suite: 34
  scenarios, 8 safety. 78 tests pass.
- 2026-11-08 - Phase 4: public `POST /v1/widget/session` (shop domain to a one-hour widget token),
  CORS for browser callers, a vanilla TypeScript widget in a shadow root (about 6 KB), read-only
  dashboard API (conversations, handoff queue, timeline from traces, cost per day), a merchant
  token CLI, and dashboard tabs for approvals, handoffs, conversations, and cost. 86 tests pass.

## Open owner decisions

- Shopify development store for the demo and the live eval run.
- Merchant sign-in: v1 uses an operator-issued merchant token pasted into the dashboard
  (`python -m app.dashboard.token`). Embedding the dashboard in Shopify admin with Shopify session
  tokens is the likely replacement; it needs a Shopify app listing decision.
- Model prices for the cost overview are config (`AGENT_*_USD_PER_MTOK`, default 0) rather than
  hardcoded, so they track Anthropic's pricing page.

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
- 2026-11-08 - The chat endpoint's tests run as the non-superuser app role. Running as the
  superuser let one store continue another store's conversation, because superusers bypass RLS.
  The conversation lookup also filters on tenant_id explicitly. The app role needs USAGE and
  SELECT on sequences (messages and traces use bigserial ids).
- 2026-11-08 - The chat API returns the full reply as JSON. Token streaming over SSE is deferred
  until the widget exists to consume it.
- 2026-11-08 - Deviation from architecture.md (flagged for the owner): an approved cancellation
  executes through the Shopify API, but approved refunds and returns are recorded as `approved`
  for the merchant to complete in Shopify admin. Partial amounts, restocking, and return labels
  need a person's judgement in v1. The agent still cannot trigger any of them.
- 2026-11-08 - Merchant and widget tokens share the signing secret but carry a role claim; each
  API accepts only its own role, so a widget token cannot approve anything.
- 2026-11-08 - The widget token endpoint is public: the widget runs on the storefront, so anyone
  may chat with a store's assistant. The token binds the session to one store and carries the
  widget role, so it cannot reach the merchant API. Per-tenant cost caps are the abuse control
  still to build.
- 2026-11-08 - CORS allows `*` by default because auth is a bearer header, never a cookie.
  Restrict with `CORS_ORIGINS` in production.
- 2026-11-08 - The widget still uses JSON replies, not SSE; streaming remains deferred.
