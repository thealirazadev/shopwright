"""stores

stores is control-plane, like tenants: rows are looked up by shop domain
before any tenant context exists (OAuth callbacks, webhook routing), so it
carries no RLS policy — see the allowlist in the RLS coverage test. Access
tokens are Fernet-encrypted before they reach this table.

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE stores (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            shop_domain text NOT NULL UNIQUE,
            access_token bytea NOT NULL,
            scopes text NOT NULL DEFAULT '',
            installed_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE stores")
