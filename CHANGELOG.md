# Changelog

## 0.2.0 - 2026-11-09

- Per-conversation token budget and per-store monthly cost cap; over either, the shopper is
  handed to a person without a model call.
- The Shopify install callback returns a clear 502 when the token exchange fails.
- API container image with a health check; CI builds it and checks it serves after migrating.
- Coverage gate at 90 percent; tests for the Claude client, Voyage embedder, OAuth routes, and the
  cancel mutation.
- Eval recordings through the Claude Code CLI (`--backend claude-code`), for running the suite
  without an API key.

## 0.1.0

Phases 0 to 4: Shopify OAuth and catalog/policy sync, hybrid retrieval, the bounded Claude agent
with citations, verified orders and merchant-approved actions, the widget, and the dashboard.
