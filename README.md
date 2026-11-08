# Shopwright

AI support copilot for Shopify and WooCommerce stores. Merchants connect their
store and get a chat widget that answers customer questions from their own
catalog, policies, and orders — embeddable with a single script tag.

**Status:** in development. Phases 1 and 2 are done: Shopify catalog and policy sync, hybrid
retrieval, a bounded Claude tool-use agent with verified citations, `POST /v1/chat` with stored
traces, and an eval suite of 30 scenarios with safety gates. Phase 3 (verified orders and
approval-gated refunds) is next. See [docs/phases.md](docs/phases.md).

## Architecture

```
React dashboard (Vercel) ──► FastAPI core API
                                │  Postgres + pgvector (Neon)
                                │  Redis (Upstash)
                                ├─► LLM client + RAG pipeline
  Shopify app (OAuth+webhooks) ─┤
  WooCommerce plugin (PHP) ─────┘
  Embeddable chat widget (vanilla JS, signed JWT)
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
| `plugin-woocommerce/` | WordPress plugin (phase 2) |
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

## Tests

```sh
cd api && uv run pytest
```

The suite includes a tenant-isolation test that proves row-level security in
Postgres — it needs the compose database running.
