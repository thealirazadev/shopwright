"""tenants and products, with row-level security

Revision ID: 0001
Revises:
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE tenants (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            name text NOT NULL,
            platform text NOT NULL CHECK (platform IN ('shopify', 'woocommerce')),
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE products (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            external_id text NOT NULL,
            title text NOT NULL,
            description text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, external_id)
        )
        """
    )

    # Tenant isolation is enforced here, in the database, not in application
    # queries (ADR-003). FORCE makes the policy apply to the table owner too;
    # missing_ok=true means "no tenant context" reads as NULL and matches
    # nothing — fail closed.
    op.execute("ALTER TABLE products ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE products FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON products
        USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE products")
    op.execute("DROP TABLE tenants")
