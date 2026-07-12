"""Every tenant-scoped table must enforce RLS — adding one without a policy fails here.

Control-plane tables are the deliberate exceptions (ADR-003): they are looked
up before any tenant context exists. Adding a table to the allowlist is a
schema-review decision, not a default.
"""

from sqlalchemy import Engine, text

CONTROL_PLANE_TABLES = {
    "stores",  # resolved by shop domain during OAuth callbacks and webhook routing
}


def test_every_tenant_scoped_table_enforces_rls(admin_engine: Engine) -> None:
    with admin_engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT c.relname, c.relrowsecurity AND c.relforcerowsecurity
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                JOIN pg_attribute a ON a.attrelid = c.oid
                WHERE n.nspname = 'public'
                  AND c.relkind = 'r'
                  AND a.attname = 'tenant_id'
                  AND NOT a.attisdropped
                """
            )
        ).fetchall()

    assert rows, "expected at least one tenant-scoped table"
    unprotected = sorted(
        name for name, enforced in rows if name not in CONTROL_PLANE_TABLES and not enforced
    )
    assert unprotected == [], (
        f"tables with tenant_id but no forced RLS policy: {unprotected} — "
        "add a policy (see migration 0001) or, if genuinely control-plane, "
        "allowlist it here with a reason"
    )
