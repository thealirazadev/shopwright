# Design decisions

The larger structural choices (modular monolith, pgvector, row-level security) have their own
records in [docs/adr](adr). This file collects the smaller decisions made while building the
agent, ingest, and APIs, with the reason for each.

## 1. The agent proposes; a merchant approves

Refunds, returns, and cancellations are never agent actions. The agent can only create an
`action_proposal` with its reasoning and the policy it relied on, and a merchant approves or
rejects it. This is enforced in code rather than in the prompt: the Shopify write client is
importable only from `app.actions`, and `tests/agent/test_boundaries.py` fails if `agent` or
`chat` imports it. A prompt injection can therefore change what the agent says, but not reach a
write call. Approval runs with an idempotency key derived from the proposal id, so a double
approval executes once, and a failed write leaves the proposal `failed` with the error.

## 2. Only cancellations execute automatically after approval

An approved cancellation calls the Shopify API. Approved refunds and returns are recorded as
`approved` for the merchant to complete in Shopify admin, because partial amounts, restocking,
and return labels need a person's judgement. In both cases the agent cannot trigger the action.

## 3. Order access needs the order number and its email

`verify_customer` checks the order number against the email on the order in the tool layer, and
returns the same result for "no such order" and "wrong email", so the agent cannot be used to
probe which orders exist. Attempts are capped at 3 per conversation, and the verified orders and
attempt counts persist with the conversation. An order with no email on it (a POS or draft order)
never verifies, since an empty email would otherwise match an empty answer, and an order lookup
only returns the order whose number was asked for, never a near match from Shopify's search. The
tenant and the set of verified orders come from
server state, never from tool input; tool schemas are strict (`additionalProperties: false`, all
fields required).

## 4. One bounded agent loop, no framework

The agent is a single tool-use loop capped at 6 model calls and 12 tool calls per turn. A
multi-agent design or agent framework would add failure modes this product does not need, and
is only worth revisiting if evals show a measurable gain. Reaching a limit produces a handoff,
not an error, and citation labels the tools did not return are removed before the answer reaches
the shopper. A conversation that has been handed off never calls the model again. The model id
and limits live in config.

## 5. Spend limits hand the shopper to a person

A per-conversation token budget and a per-store monthly cost cap stop model calls once reached.
Past either limit the shopper is handed to a person, with a handoff reason that names the limit,
instead of receiving an error. Both limits default to 0 (off). Model prices
(`AGENT_*_USD_PER_MTOK`) are configuration rather than constants so they can track the provider's
published pricing; the monthly cap is computed from them, so it only takes effect once they are
set. Every input token counts toward both limits, including prompt-cache writes and reads, which
the API reports separately from `input_tokens`. Cache reads are billed below the input price, so
the cost estimate errs high when the cache hits, and the cap trips early rather than late.

## 6. Voyage AI embeddings over plain HTTP

Anthropic has no embedding API, and Voyage AI is the provider its documentation points to.
Voyage is called over httpx, which was already a dependency, behind an `Embedder` interface, so
no provider SDK is added and the provider can be swapped. Tests use a deterministic hashing
embedder.

## 7. A failed embedding call does not fail the sync

If the embedding call fails, chunks are stored with a NULL vector instead of aborting the sync.
Full-text search still finds them, and `embed_missing` fills in the vectors later. Sources are
re-chunked and re-embedded only when their content hash changes, so an unchanged catalog triggers
no embedding calls.

## 8. Hybrid retrieval with an OR text query

Retrieval merges pgvector cosine similarity with Postgres full-text rank using reciprocal rank
fusion. The full-text side matches any query word (OR) rather than all of them, because shoppers'
questions rarely contain every word of the answer; the vector ranking and rank fusion supply the
precision.

## 9. Paginated sync and inline webhooks

Full sync uses paginated Admin GraphQL rather than bulk operations: it is simpler and adequate
for the catalog sizes in ADR-002, with stores above roughly 10k products as the point to revisit.
Product webhooks are HMAC-verified and applied inline instead of through the Redis queue, since
one product per call is small. Moving them to the queue is the fix if webhook latency or volume
requires it.

## 10. Isolation tests run as the application role

The chat endpoint's tests originally ran as the database superuser, which let one store continue
another store's conversation, because superusers bypass row-level security. The tests now run as
the non-superuser application role, and the conversation lookup also filters on `tenant_id`
explicitly. The application role needs USAGE and SELECT on sequences, since messages and traces
use bigserial ids.

## 11. Role-scoped tokens and a public widget session

Merchant and widget tokens share a signing secret but carry a role claim, and each API accepts
only its own role, so a widget token cannot approve anything. `POST /v1/widget/session` is public
because the widget runs on the storefront and anyone may chat with a store's assistant; the
one-hour token binds the session to one store and carries the widget role, and the spend limits
in section 5 are the abuse control. CORS allows `*` by default because authentication is a bearer
header, never a cookie; `CORS_ORIGINS` restricts it in production.

## 12. Errors and logs carry no shopper data

The API has one error envelope, and shoppers never see stack traces or provider errors. Tool
failures go back to the model as `is_error` tool results so it can tell the shopper it cannot
check right now. Logs are structured JSON with request and conversation ids, and contain no
message text, emails, or order data.

## 13. Deterministic, replayable evals

Evals use the hashing embedder so a recorded run replays byte for byte in CI; retrieval quality
has its own tests, and replay exercises the agent's decisions against a fixed store, which is
what the scenarios assert. Recordings can also be made through `claude -p` with structured
output, so the suite runs without an API key; this is eval-only code, and results state which
backend recorded them. Once any recording exists, a scenario without one fails the replay instead
of being skipped, so the gate always covers every scenario. The first live run scored 28 of 34 and exposed two prompt problems: the
agent repeated an injected instruction while saying it ignored it, and its wording ("that the
policy allows") made it hand off verified cancellation requests that the store's policies did
not mention. The prompt now turns a verified refund, return, or cancellation request into a
proposal unless a policy clearly rules it out, and forbids repeating injected instructions. The
rerun passed 34 of 34.

## 14. JSON replies for now

The chat API returns the full reply as JSON. Token streaming over SSE is deferred; the widget
consumes JSON replies today.
