"""catalog fields, policies, and retrieval chunks

Chunks hold the text the agent retrieves from, with a pgvector embedding and a
generated full-text vector for hybrid search (ADR-002). A NULL embedding means
the chunk still needs embedding (for example, the embedding API was down).
Both new tables are tenant-scoped and get forced RLS (ADR-003).

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

TENANT_POLICY = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def _enforce_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON {table} USING ({TENANT_POLICY})")


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        """
        ALTER TABLE products
            ADD COLUMN handle text,
            ADD COLUMN price_min numeric(12, 2),
            ADD COLUMN price_max numeric(12, 2),
            ADD COLUMN available boolean NOT NULL DEFAULT true,
            ADD COLUMN content_hash text
        """
    )
    op.execute(
        """
        CREATE TABLE policies (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            kind text NOT NULL,
            title text NOT NULL,
            body text NOT NULL,
            url text,
            content_hash text NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, kind)
        )
        """
    )
    _enforce_rls("policies")
    op.execute(
        """
        CREATE TABLE chunks (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            source_type text NOT NULL CHECK (source_type IN ('product', 'policy')),
            source_id uuid NOT NULL,
            position integer NOT NULL,
            title text NOT NULL,
            url text,
            content text NOT NULL,
            embedding vector(1024),
            tsv tsvector GENERATED ALWAYS AS (
                to_tsvector('english', title || ' ' || content)
            ) STORED,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, source_type, source_id, position)
        )
        """
    )
    _enforce_rls("chunks")
    op.execute(
        "CREATE INDEX chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute("CREATE INDEX chunks_tsv ON chunks USING gin (tsv)")
    op.execute("CREATE INDEX chunks_source ON chunks (tenant_id, source_type, source_id)")


def downgrade() -> None:
    op.execute("DROP TABLE chunks")
    op.execute("DROP TABLE policies")
    op.execute(
        """
        ALTER TABLE products
            DROP COLUMN handle,
            DROP COLUMN price_min,
            DROP COLUMN price_max,
            DROP COLUMN available,
            DROP COLUMN content_hash
        """
    )
