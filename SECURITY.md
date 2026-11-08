# Security

## Reporting a vulnerability

Report vulnerabilities privately through GitHub: **Security > Report a vulnerability** on this
repository. Do not open a public issue. You will get a reply within five working days.

Supported: the `main` branch.

## Security model

- **Tenant isolation.** Every store-owned table has Postgres row-level security, forced, keyed on
  a per-request tenant setting; the app runs as a non-superuser role. A test fails if a new table
  lacks a policy (`tests/test_rls_coverage.py`). See [docs/adr](docs/adr).
- **The agent cannot change orders.** Refunds, returns, and cancellations are proposals that a
  merchant approves. The Shopify write client is importable only from `app.actions`, enforced by
  `tests/agent/test_boundaries.py`, so a prompt injection cannot reach it.
- **Order privacy.** Orders are shown only after the shopper gives the order number and its email;
  a wrong email and an unknown order get the same reply, and attempts are limited per
  conversation.
- **Store content is untrusted.** Product and policy text reaches the model as tool results that
  the system prompt marks as data; injection scenarios are part of the eval safety gate.
- **Credentials.** Shopify access tokens are encrypted at rest (Fernet). OAuth callbacks are
  HMAC-verified with a signed, expiring state; webhooks are HMAC-verified.
- **Tokens.** Widget and merchant tokens are signed, short-lived, and carry a role; each API
  accepts only its own role.
- **Spend limits.** `CONVERSATION_TOKEN_BUDGET` and `TENANT_MONTHLY_COST_CAP_USD` stop model calls
  and hand the shopper to a person once reached, so a public widget cannot run up unbounded cost.
