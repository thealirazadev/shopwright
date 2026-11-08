"""verified orders per conversation, and action proposals

The agent can only see an order after the shopper verifies it in the same
conversation, and can only *propose* refunds, returns, and cancellations. A
proposal executes once, after a merchant approves it (see app/actions).

Revision ID: 0005
Revises: 0004
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

TENANT_POLICY = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE conversations
            ADD COLUMN verified_orders text[] NOT NULL DEFAULT '{}',
            ADD COLUMN verify_attempts integer NOT NULL DEFAULT 0
        """
    )
    op.execute(
        """
        CREATE TABLE action_proposals (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            conversation_id uuid NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            kind text NOT NULL CHECK (kind IN ('refund', 'return', 'cancel')),
            order_ref text NOT NULL,
            reason text NOT NULL,
            policy_sources jsonb NOT NULL DEFAULT '[]',
            status text NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'approved', 'rejected', 'executed', 'failed')),
            decided_by text,
            decided_at timestamptz,
            execution_error text,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("ALTER TABLE action_proposals ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE action_proposals FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON action_proposals USING ({TENANT_POLICY})")
    op.execute("CREATE INDEX action_proposals_status ON action_proposals (tenant_id, status)")


def downgrade() -> None:
    op.execute("DROP TABLE action_proposals")
    op.execute("ALTER TABLE conversations DROP COLUMN verified_orders, DROP COLUMN verify_attempts")
