# ADR-003: Tenant isolation via Postgres row-level security

Status: accepted · Date: 2026-07-07

## Context

Shopwright is multi-tenant: every store's products, conversations, and
embeddings live in shared tables. The worst possible failure for this product
is one merchant's data appearing in another merchant's chat widget. Filtering
by `tenant_id` in application queries is necessary but not sufficient — a
single forgotten `WHERE` clause anywhere in the codebase becomes a data leak.

## Decision

Enforce isolation in the database with row-level security, not just in the ORM:

- Every tenant-scoped table gets `ENABLE ROW LEVEL SECURITY` **and**
  `FORCE ROW LEVEL SECURITY` (so even the table owner is subject to policies),
  with a policy matching rows against `current_setting('app.tenant_id')`.
- The application sets the tenant with `set_config('app.tenant_id', …, true)`
  at the start of each transaction — transaction-local, so nothing leaks
  across pooled connections.
- The setting is read with `current_setting(…, missing_ok := true)`, which
  returns NULL when unset: **no tenant context means no rows**. Fail closed.
- The application connects as a dedicated non-superuser role. Superuser and
  `BYPASSRLS` roles are for migrations and operations only, never the app path.
- ORM-level tenant filters remain as a convenience, but they are not the
  security boundary.

An automated test proves the isolation: it connects as the application role
and verifies that cross-tenant reads return nothing, cross-tenant writes are
rejected, and queries without tenant context return nothing. It runs in CI on
every change.

## Consequences

- Adding a tenant-scoped table carries a checklist: RLS enabled + forced,
  policy created, covered by the isolation test. Schema review enforces this.
- Connection discipline matters: the tenant GUC must be set inside the
  transaction that uses it. A helper owns this so call sites can't get it wrong.
- The application role must be provisioned per environment (it's created
  locally by the test suite; in Neon it's created once via SQL). Credentials
  for it live in `DATABASE_URL` like any other secret.
- Cross-tenant admin/analytics queries need an explicit separate path with its
  own role — which is the point.
