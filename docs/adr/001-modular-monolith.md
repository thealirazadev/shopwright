# ADR-001: Modular monolith over microservices

Status: accepted · Date: 2026-07-07

## Context

Shopwright has several clearly separable domains: store connectors
(Shopify/WooCommerce), content ingestion and embedding, RAG retrieval, chat,
and later billing and admin. The obvious question is whether these become
services or modules.

This is a one-person project. Every additional deployable multiplies the
operational surface: separate deploys, separate logs, network failure modes
between components, and versioned contracts where a function call would do.
The expected load (tens of stores, not thousands) doesn't justify independent
scaling of any component.

## Decision

One FastAPI application, structured as a modular monolith. Domains live in
separate packages (`connectors/`, `ingest/`, `rag/`, `chat/`, `billing/`,
`admin/`) with module-local models and explicit interfaces between them.
Background work goes through a Redis queue rather than a separate worker
service until measurement says otherwise.

## Consequences

- One deploy, one log stream, one place to debug. Transactions can span
  domains when needed (e.g. product update + embedding invalidation).
- The risk is module boundaries eroding into a tangle. Guardrails: modules
  expose a small public interface, don't import each other's internals, and
  boundary violations are treated as review blockers.
- If a component ever needs independent scaling (most likely ingest), the
  module boundary is the extraction seam. That decision would get its own ADR
  with load numbers attached.
