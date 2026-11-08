# Project Memory - Shopwright

Running log of what is done, in progress, and decided. Keep entries short and dated.

## Completed

- 2026-07-12 - Phase 0: FastAPI scaffold, tenant/product/store schema with forced RLS and an
  isolation test, Shopify OAuth with encrypted tokens, dashboard scaffold, CI.
- 2026-11-08 - Planning docs added: PRD, architecture, phases, rules, testing. Awaiting owner
  review before phase 1.

## Open owner decisions

- Embedding provider for production (Anthropic has no embedding API; a hosted provider is needed).
- Default model id for the agent.
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
