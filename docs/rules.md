# Engineering Rules - Shopwright

## Conventions

- Modules follow ADR-001: no imports of another module's internals; `agent` never imports the
  Shopify write client or `actions.execute`.
- Every tenant-scoped table follows the ADR-003 checklist in the same commit that creates it.
- Tool schemas are strict (`additionalProperties: false`, all fields required). The tenant and the
  verified-order set come from server state, never from tool input.
- The model id, limits, and cost caps live in config, not in code.

## Error handling & logging

- One error envelope for the API. Shoppers never see stack traces or provider errors.
- Tool failures go back to the model as `is_error` tool results.
- Structured JSON logs with request and conversation ids; no message text, emails, or order data
  in logs.

## Security

- Safety properties are enforced in code and proven by tests, not only stated in the prompt:
  verification before order data, approval before writes, tenant isolation.
- Store content (descriptions, reviews, policies) is untrusted input.
- Secrets in `.env` only; Shopify tokens encrypted at rest (exists).

## Simplicity / YAGNI-KISS

- One agent, one loop. No agent framework and no multi-agent orchestration unless an eval shows a
  measurable gain.
- No new dependency without owner approval.

## Code style

- ruff, black, and mypy clean. Short conventional commits, one task per commit, no emoji.

## Boundaries - never do without asking the owner first

- Add a tool that writes anything other than a proposal or a handoff.
- Lower an eval safety gate or delete a scenario.
- Change ADRs, the PRD, or this file.
