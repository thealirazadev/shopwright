# Testing - Shopwright

## Strategy

Three layers: unit tests for pure logic, integration tests against the compose Postgres with the
application role (so RLS is always in force), and the eval suite for agent behavior. No test calls
Shopify or the model API; both are faked or replayed.

## What gets unit coverage

Chunking and content hashing, reciprocal rank fusion, citation filtering, tool argument
validation, loop limits, cost calculation, widget token signing.

## What gets integration coverage

Webhook HMAC, sync and re-embedding, retrieval isolation between tenants, verified-order checks,
proposal state transitions and idempotent execution, the agent import boundary, SSE streaming.

## Evals

- `uv run python -m evals.run` replays recorded model responses (CI, free, deterministic).
- `uv run python -m evals.run --live` calls the real model, records fixtures, and prints cost.
- Safety gates fail on any single violation. Quality metrics compare against
  `evals/baseline.json`; updating the baseline is a reviewed commit.

## Exact commands

```sh
docker compose up -d
cd api && uv run ruff check . && uv run black --check . && uv run mypy app && uv run pytest
uv run python -m evals.run
```

## CI plan

Existing workflow plus the offline eval run. The live eval stays manual.

## Definition of done for a feature

Tests for the behavior, isolation covered for new tables, eval scenarios for new agent behavior,
docs/memory.md updated, CI green.
