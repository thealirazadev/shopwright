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
proposal state transitions and idempotent execution, the agent import boundary.

## Evals

- `uv run python -m evals.run` replays recorded model responses (CI, free, deterministic).
- `uv run python -m evals.run --live` calls the real model, records fixtures, and prints cost.
- `uv run python -m evals.run --live --backend claude-code` records through the Claude Code CLI
  instead of the API.
- Scenarios marked safety are a hard gate: any single violation fails the run. The remaining
  scenarios must pass at `MIN_PASS_RATE` (90 percent) in `evals/run.py`.

## Exact commands

```sh
docker compose up -d
cd api && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
uv run python -m evals.run
```

## CI

`.github/workflows/ci.yml` runs lint, format check, type check, tests, and the offline eval replay
against a pgvector Postgres service, builds the API image and checks that it migrates and answers
`/health`, and builds the dashboard and widget. The live eval run is manual.

New tables come with isolation coverage, and new agent behavior comes with eval scenarios.
