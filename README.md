# Shopwright

AI support copilot for Shopify stores. Merchants connect their store and get a chat widget that
answers customer questions from their own catalog, policies, and orders, embeddable with a single
script tag. A WooCommerce plugin is planned.

**Status:** phases 1 to 4 are done.

- Shopify catalog and policy sync, and hybrid retrieval (pgvector plus full-text, rank fusion).
- A bounded Claude tool-use agent with verified citations, and an eval suite of 34 scenarios with
  safety gates that runs in CI.
- The agent verifies the shopper before showing any order. Refunds, returns, and cancellations are
  proposals a merchant approves; the agent's code cannot reach Shopify's write API.
- Every store's data is isolated with Postgres row-level security.
- An embeddable widget and a merchant dashboard (approvals, handoffs, conversation timelines,
  daily cost).
- Spend limits: a token budget per conversation and a monthly cost cap per store. Past either,
  the shopper is handed to a person and the model is not called.

See [docs/phases.md](docs/phases.md).

## Architecture

```
React dashboard (Vercel) ──► FastAPI core API
                                │  Postgres + pgvector (Neon)
                                │  Redis (Upstash)
                                ├─► LLM client + RAG pipeline
  Shopify app (OAuth+webhooks) ─┤
  WooCommerce plugin (planned) ──┘
  Embeddable chat widget (vanilla TS, signed per-store token)
```

The API is a modular monolith — see [docs/adr](docs/adr) for why, and for the
other decisions that shape this repo (pgvector over a dedicated vector DB,
row-level security for tenant isolation).

## Repo layout

| Path | What it is |
|---|---|
| `api/` | FastAPI core — connectors, ingest, RAG, chat |
| `dashboard/` | Merchant dashboard (React + TypeScript + Tailwind) |
| `widget/` | Embeddable chat widget (vanilla TS) |
| `plugin-woocommerce/` | WordPress plugin (planned, not started) |
| `docs/adr/` | Architecture decision records |

## Local development

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/), Node 22+, and Docker.

```sh
docker compose up -d          # Postgres (pgvector) + Redis
cp .env.example .env

cd api
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload

cd ../dashboard
npm install
npm run dev
```

## Run with Docker

```sh
docker build -t shopwright-api api
docker run -p 8000:8000 --env-file .env shopwright-api   # migrates, then serves; GET /health
```

## Tests

```sh
cd api && uv run pytest
```

The suite includes a tenant-isolation test that proves row-level security in
Postgres — it needs the compose database running. Coverage is gated at 90 percent.

Agent evals replay recorded model replies in CI (`uv run python -m evals.run`). To re-record,
run `--live` with `ANTHROPIC_API_KEY`, or `--live --backend claude-code` to go through the
Claude Code CLI instead. Security model: [SECURITY.md](SECURITY.md).
