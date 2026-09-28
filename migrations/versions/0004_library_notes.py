"""Library notes per pinned Lean environment, read within their experiment (S1 audit #24)."""

import sqlalchemy as sa
from alembic import op

revision = "0004_library_notes"
down_revision = "0003_discussion_indexes"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "library_notes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(200), nullable=False),
        sa.Column("environment_digest", sa.String(64), nullable=False),
        sa.Column("experiment_id", sa.String(36), nullable=False),
        sa.Column("author", sa.String(200), nullable=False),
        sa.Column("text", sa.String(2000), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
    )
    op.create_index(
        "library_notes_experiment_environment",
        "library_notes",
        ["project_id", "experiment_id", "environment_digest", "created_at"],
    )


def downgrade():
    op.drop_index("library_notes_experiment_environment", table_name="library_notes")
    op.drop_table("library_notes")
