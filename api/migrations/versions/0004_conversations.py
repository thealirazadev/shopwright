"""conversations, messages, and traces

Messages keep the exact content blocks exchanged with the model so a
conversation can be resumed and replayed. Traces hold one row per model call
and per tool call. All three are tenant-scoped with forced RLS (ADR-003).

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

TENANT_POLICY = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def _enforce_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON {table} USING ({TENANT_POLICY})")


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE conversations (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'handoff')),
            handoff_reason text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE messages (
            id bigserial PRIMARY KEY,
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            conversation_id uuid NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            role text NOT NULL CHECK (role IN ('user', 'assistant')),
            content jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE traces (
            id bigserial PRIMARY KEY,
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            conversation_id uuid NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            turn integer NOT NULL,
            kind text NOT NULL,
            name text NOT NULL,
            detail jsonb NOT NULL DEFAULT '{}',
            latency_ms integer NOT NULL,
            input_tokens integer NOT NULL DEFAULT 0,
            output_tokens integer NOT NULL DEFAULT 0,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    for table in ("conversations", "messages", "traces"):
        _enforce_rls(table)
    op.execute("CREATE INDEX messages_conversation ON messages (conversation_id, id)")
    op.execute("CREATE INDEX traces_conversation ON traces (conversation_id, turn)")


def downgrade() -> None:
    op.execute("DROP TABLE traces")
    op.execute("DROP TABLE messages")
    op.execute("DROP TABLE conversations")
