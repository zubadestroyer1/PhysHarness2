"""Initial canonical schema frozen on 2026-09-14.

Includes token ledger columns. Never import runtime metadata into a migration.
"""

import sqlalchemy as sa
from alembic import op

revision = "0001_canonical_store"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(50), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.CheckConstraint("revision >= 1", name="records_positive_revision"),
    )
    op.create_index("ix_records_project_id", "records", ["project_id"])
    op.create_index("ix_records_kind", "records", ["kind"])
    op.create_index("records_project_kind", "records", ["project_id", "kind"])
    op.create_table(
        "commands",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.String(200), nullable=False),
        sa.Column("operation_id", sa.String(36), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
    )
    op.create_index("ix_commands_project_id", "commands", ["project_id"])
    op.create_table(
        "events",
        sa.Column("sequence", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(100), nullable=False),
        sa.Column("aggregate_id", sa.String(36), nullable=False),
        sa.Column("operation_id", sa.String(36), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
    )
    for name in ["project_id", "aggregate_id", "operation_id"]:
        op.create_index(f"ix_events_{name}", "events", [name])
    op.create_table(
        "outbox",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(100), nullable=False),
        sa.Column("aggregate_id", sa.String(36), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_until", sa.Float(), nullable=False, server_default="0"),
        sa.Column("owner", sa.String(200), nullable=True),
        sa.Column("last_error", sa.String(2000), nullable=True),
    )
    op.create_index("ix_outbox_project_id", "outbox", ["project_id"])
    op.create_index("ix_outbox_state", "outbox", ["state"])
    op.create_table(
        "budgets",
        sa.Column("experiment_id", sa.String(36), primary_key=True),
        sa.Column("max_cost", sa.BigInteger(), nullable=False),
        sa.Column("reserved", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("spent", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("active_workers", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_concurrency", sa.Integer(), nullable=False),
        sa.Column("max_tokens", sa.BigInteger(), nullable=True),
        sa.Column("tokens_reserved", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("tokens_spent", sa.BigInteger(), nullable=False, server_default="0"),
        sa.CheckConstraint(
            "max_cost >= 0 AND reserved >= 0 AND spent >= 0", name="budget_costs_nonnegative"
        ),
        sa.CheckConstraint(
            "active_workers >= 0 AND max_concurrency > 0", name="budget_worker_counts_valid"
        ),
        sa.CheckConstraint(
            "tokens_reserved >= 0 AND tokens_spent >= 0 "
            "AND (max_tokens IS NULL OR max_tokens >= 0)",
            name="budget_tokens_nonnegative",
        ),
    )
    op.create_table(
        "reservations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("experiment_id", sa.String(36), nullable=False),
        sa.Column("reserved", sa.BigInteger(), nullable=False),
        sa.Column("workers", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False, server_default="active"),
        sa.Column("actual", sa.BigInteger(), nullable=True),
        sa.Column("tokens_reserved", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("tokens_actual", sa.BigInteger(), nullable=True),
        sa.CheckConstraint(
            "reserved >= 0 AND workers >= 0 AND (actual IS NULL OR actual >= 0)",
            name="reservation_amounts_nonnegative",
        ),
        sa.CheckConstraint(
            "tokens_reserved >= 0 AND (tokens_actual IS NULL OR tokens_actual >= 0)",
            name="reservation_tokens_nonnegative",
        ),
    )
    op.create_index("ix_reservations_experiment_id", "reservations", ["experiment_id"])
    op.create_table(
        "leases",
        sa.Column("task_id", sa.String(36), primary_key=True),
        sa.Column("holder", sa.String(200), nullable=False),
        sa.Column("fence", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.Float(), nullable=False),
    )
    op.create_table(
        "dependencies",
        sa.Column("source_id", sa.String(36), primary_key=True),
        sa.Column("target_id", sa.String(36), primary_key=True),
        sa.Column("relation", sa.String(50), primary_key=True),
        sa.Column("project_id", sa.String(200), nullable=False),
    )
    op.create_index("ix_dependencies_project_id", "dependencies", ["project_id"])


def downgrade():
    for table in [
        "dependencies",
        "leases",
        "reservations",
        "budgets",
        "outbox",
        "events",
        "commands",
        "records",
    ]:
        op.drop_table(table)
