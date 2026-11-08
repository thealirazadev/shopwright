# Architecture - Shopwright

Builds on ADR-001 (modular monolith), ADR-002 (pgvector), and ADR-003 (row-level security). Every
tenant-scoped table below follows the ADR-003 checklist: RLS enabled and forced, policy on
`app.tenant_id`, covered by the isolation test.

## App flow

```
Shopper ─► widget (signed JWT, per store) ─► POST /v1/chat (SSE)
                                                 │
                                    agent loop (api/app/agent)
                                    │   model: Claude, tool use
                                    ├─► catalog tools ─► pgvector + products
                                    ├─► policy tools  ─► pgvector + policy chunks
                                    ├─► order tools   ─► Shopify Admin API (read only)
                                    ├─► propose_action ─► action_proposals (pending)
                                    └─► handoff        ─► conversation status = handoff
Merchant ─► dashboard ─► approvals queue ─► approve ─► Shopify Admin API (write)
Shopify webhooks ─► ingest queue ─► chunk + embed ─► chunks table
```

## Modules

| Module | Owns |
|---|---|
| `connectors/shopify` | OAuth (exists), Admin API client split into a read client and a write client, webhooks |
| `ingest` | Product and policy sync, chunking, embedding, re-embedding on change |
| `rag` | Hybrid retrieval (vector plus keyword), returns chunks with stable source ids |
| `agent` | The loop, tool definitions, system prompt, guardrails, traces |
| `actions` | Proposals, approval and rejection, executing approved actions with the write client |
| `chat` | HTTP and SSE endpoints, widget token verification, conversation storage |

`agent` may import the read client and `actions.propose`. It may not import the write client or
`actions.execute`; an import-boundary test enforces this.

## Agent loop

One request = one shopper message. The loop runs until the model ends its turn, with hard limits:

- At most 6 model calls per shopper message and 12 tool calls; on the limit the agent apologizes
  and hands off.
- A per-conversation token budget and a per-tenant monthly cost cap; over the cap, the widget
  shows a handoff message instead of calling the model.
- Tool calls run sequentially, each with a timeout. A tool error is returned to the model as an
  `is_error` tool result, never raised to the shopper.
- Streaming: text deltas stream to the widget; tool calls appear as short status lines ("Checking
  your order").

Model access goes through one client module with the model id in config, so the model can change
without touching the loop.

## Tools

All tool inputs use strict JSON schemas with `additionalProperties: false`. The tenant comes from
the verified widget token, never from tool input.

| Tool | Reads or writes | Notes |
|---|---|---|
| `search_catalog(query, limit)` | read | Hybrid search over product chunks; returns product ids, titles, prices, availability, source ids |
| `get_product(product_id)` | read | Current variants, stock, and options |
| `search_policies(query, limit)` | read | Policy chunks with source ids, used for returns, shipping, warranty |
| `verify_customer(order_number, email)` | read | Matches both against Shopify; on success marks the conversation verified for that order only. Rate limited per conversation and per IP. Responds the same way whether the order is missing or the email is wrong |
| `get_order(order_number)` | read | Allowed only for an order verified in this conversation; otherwise returns an error result |
| `propose_action(kind, order_number, line_items, reason, policy_source_ids)` | writes a proposal only | `kind` is refund, return, or cancel. Requires a verified order. Creates a pending proposal; tells the shopper a person will review it |
| `handoff(reason)` | writes conversation status | Ends agent handling; the merchant sees it in the queue |

## Guardrails

- **Store content is data.** Product descriptions, reviews, and policy text are passed inside tool
  results and the system prompt says instructions found there are not to be followed. Eval
  scenarios plant instructions in product descriptions to prove it.
- **Identity before order data.** Enforced in the tool layer, not just the prompt: `get_order` and
  `propose_action` check the conversation's verified-order set in code.
- **No money movement from the agent.** Write calls exist only in `actions.execute`, reachable only
  from an authenticated merchant approval.
- **Grounding.** The system prompt requires citing source ids for factual claims; the response
  renderer drops any citation id that was not returned by a tool in this conversation.
- **PII.** Logs carry ids, not message text. Traces store message text inside the tenant's RLS
  scope; retention is configurable per tenant (default 90 days).

## Action proposals

`action_proposals`: id, tenant_id, conversation_id, kind, order_ref, line_items (jsonb), amount,
reason, policy_source_ids, status (`pending`, `approved`, `rejected`, `executed`, `failed`),
decided_by, decided_at, execution_error, created_at.

Approval runs in one transaction: conditional update `pending -> approved` (one winner), then the
write call, then `approved -> executed` or `failed` with the error. The Shopify call carries an
idempotency key derived from the proposal id, so a retried approval cannot refund twice.

## Retrieval

- Chunks: products (title, description, options, price), policy pages, and FAQ pages, about 300
  to 500 tokens each, with `source_type`, `source_id`, `source_url`, and a content hash.
- Re-embed only when the content hash changes, in the same transaction as the source update
  (ADR-002).
- Hybrid query: pgvector cosine similarity plus Postgres full-text rank, merged with reciprocal
  rank fusion. Product availability comes from `get_product` at answer time, never from stale
  chunks.
- Embeddings go through an `Embedder` interface. Production uses a hosted embedding API (provider
  choice is an owner decision, logged in memory); tests use a deterministic fake.

## Traces

`traces`: one row per model call and per tool call, with conversation_id, turn, kind, name,
input (jsonb), output (jsonb, truncated), tokens in and out, cost, latency_ms, error. Cost uses
provider-reported usage. The dashboard renders a conversation as a timeline from these rows.

## Evals

- Scenarios live in `evals/scenarios/*.yaml`: a seeded store fixture, a shopper script, and
  assertions: expected tools called and not called, required citation sources, forbidden content
  (order fields when unverified), and an LLM-judge rubric for answer quality.
- Offline mode replays recorded model responses so CI is deterministic and free. Live mode calls
  the real model and records new fixtures; it is run manually and reports cost.
- Safety assertions (unverified disclosure, write without approval, followed injected
  instruction) are hard gates: any single failure fails CI. Quality metrics gate on a stored
  baseline.

## Failure modes

| Failure | Behavior |
|---|---|
| Model API error or timeout | One retry with backoff, then a handoff message; trace records the error |
| Shopify API error on a read tool | `is_error` tool result; the model tells the shopper it cannot check right now |
| Shopify error on an approved action | Proposal `failed` with the error; merchant sees it and can retry with the same idempotency key |
| Embedding API down during sync | Source row saved, chunk marked stale, retried by the queue; retrieval skips stale chunks |
| Tenant over cost cap | No model call; handoff message |
| Missing tenant context | RLS returns nothing (fail closed); request errors, never another tenant's data |

## Tech stack with rationale

Existing: FastAPI, SQLAlchemy, Alembic, Postgres with pgvector, Redis, React and TypeScript
dashboard, vanilla TypeScript widget. Added: the Anthropic Python SDK for the agent (tool use
and streaming), and one embedding client. Any new dependency needs owner approval first.
