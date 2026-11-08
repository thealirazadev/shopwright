# Phases - Shopwright

Rule: phase N+1 does not start until the owner approves phase N. One commit per task. Each phase
ends with lint, typecheck, and tests green in CI.

## Phase 0 - Foundation (done)

FastAPI scaffold, tenant and product schema with forced RLS, isolation test, stores table, Shopify
OAuth with encrypted tokens, dashboard scaffold, CI.

## Phase 1 - Catalog and policy ingest with retrieval (done)

### Tasks

- Shopify read client (Admin GraphQL) with retries and rate-limit handling.
- Product sync (paginated GraphQL full sync plus `products/*` webhooks with HMAC verification)
  and policy sync.
- `chunks` table (RLS) with pgvector HNSW index and full-text index; content-hash re-embedding.
- `Embedder` interface with a deterministic fake for tests and one hosted provider.
- Hybrid retrieval with reciprocal rank fusion.

### Expected commits

1. `feat(shopify): add read-only admin api client`
2. `feat(rag): add policies and chunks tables with vector and text indexes`
3. `feat(rag): add embedders and chunking`
4. `feat(ingest): sync products and policies, embedding changed content only`
5. `feat(ingest): verify and apply product webhooks`
6. `feat(rag): add hybrid retrieval`

Each commit carries its own tests.

### Verification checklist

- [x] Webhook with a bad HMAC is rejected; a valid one updates the product and re-embeds only it.
- [x] Unchanged content triggers no embedding calls.
- [x] Retrieval returns the right product for 10 seeded queries (fixture store, hashing embedder).
- [x] Chunks of store A never appear in store B's retrieval.
- [ ] Full sync against a real Shopify development store (needs the store).

## Phase 2 - Agent core with catalog and policy tools, plus the eval harness (in progress)

### Tasks

- Model client module; agent loop with turn, tool, and token limits.
- `search_catalog`, `get_product`, `search_policies`, `handoff` tools with strict schemas.
- `conversations`, `messages`, `traces` tables (RLS); `POST /v1/chat` with SSE.
- Citation rendering that drops ids not returned by tools.
- Eval harness: scenario format, offline replay, live recording, first 30 scenarios (answerable,
  unanswerable, handoff, injected instructions in product descriptions).

### Expected commits

1. `feat(agent): add model client and bounded agent loop`
2. `feat(agent): add catalog and policy tools`
3. `feat(chat): add conversations, messages, and traces`
4. `feat(chat): stream agent turns over sse`
5. `feat(agent): render only verified citations`
6. `feat(evals): add scenario runner with offline replay`
7. `test(evals): add first 30 scenarios and ci gate`

### Verification checklist

- [ ] Every factual answer in the offline suite cites a returned source (needs a live recording).
- [ ] Unanswerable scenarios are declined, not guessed (needs a live recording).
- [ ] Injected instructions in product data are never followed (needs a live recording).
- [x] Turn limit reached produces a handoff, not an error.
- [x] Invented citation labels are removed before the answer reaches the shopper.
- [ ] Trace rows reconstruct each conversation; cost equals reported usage.

## Phase 3 - Verified orders, action proposals, approvals

### Tasks

- `verify_customer`, `get_order` with code-level verified-order checks and rate limits.
- `action_proposals` table and `propose_action` tool.
- Merchant approval endpoint; execution with the write client and idempotency keys.
- Import-boundary test: the agent package cannot reach the write client.
- 30 more eval scenarios: unverified access attempts, social engineering, refund outside policy,
  partial refunds.

### Expected commits

1. `feat(agent): verify customers before order access`
2. `feat(agent): add read-only order tool`
3. `feat(actions): add proposals and the propose_action tool`
4. `feat(actions): execute approved proposals idempotently`
5. `test(actions): prove the agent cannot reach write calls`
6. `test(evals): add order and action scenarios`

### Verification checklist

- [ ] Zero order fields disclosed in every unverified scenario.
- [ ] A double approval executes once; a failed write leaves the proposal `failed` and retryable.
- [ ] The boundary test fails if `agent` imports the write client.

## Phase 4 - Widget and dashboard

### Tasks

- Widget token issuing and verification (short-lived, per store); embeddable widget.
- Dashboard: conversations timeline from traces, approvals queue, handoff queue, cost per day.

### Expected commits

1. `feat(chat): issue and verify widget tokens`
2. `feat(widget): add embeddable chat widget`
3. `feat(dashboard): add conversation timeline`
4. `feat(dashboard): add approvals and handoff queues`
5. `feat(dashboard): add cost overview`

### Verification checklist

- [ ] A token for store A cannot read store B.
- [ ] Approving from the dashboard executes the action exactly once.

## Phase 5 - Launch: published results

### Tasks

- Live eval run on the full suite; publish accuracy, safety gates, cost per conversation, and p95
  latency in the README with the date and model id.
- Demo against a Shopify development store; README demo video and screenshots.

### Expected commits

1. `docs: publish eval results`
2. `docs: add demo and setup guide`

## Phase 6 - WooCommerce connector

Planned after launch; scoped in its own update to this file.
