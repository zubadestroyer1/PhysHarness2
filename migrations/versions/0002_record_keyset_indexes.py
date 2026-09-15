"""Ordered record indexes, including immutable JSON experiment scope expressions."""

import sqlalchemy as sa
from alembic import op

revision = "0002_record_keyset_indexes"
down_revision = "0001_canonical_store"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("records_project_kind_keyset", "records", ["project_id", "kind", "id"])
    experiment = sa.column("payload", sa.JSON())["experiment_id"].as_string()
    op.create_index(
        "records_project_kind_experiment_keyset",
        "records",
        ["project_id", "kind", experiment, "id"],
    )
    payload = sa.column("payload", sa.JSON())
    op.create_index(
        "records_project_kind_problem_keyset",
        "records",
        ["project_id", "kind", payload["problem_id"].as_string(), "id"],
    )
    op.create_index(
        "records_project_kind_artifact_review",
        "records",
        [
            "project_id",
            "kind",
            payload["artifact_id"].as_string(),
            payload["review_id"].as_string(),
        ],
    )


def downgrade():
    op.drop_index("records_project_kind_problem_keyset", table_name="records")
    op.drop_index("records_project_kind_artifact_review", table_name="records")
    op.drop_index("records_project_kind_experiment_keyset", table_name="records")
    op.drop_index("records_project_kind_keyset", table_name="records")
