"""Bounded research-board event and reader lookups."""

import sqlalchemy as sa
from alembic import op

revision = "0003_discussion_indexes"
down_revision = "0002_record_keyset_indexes"
branch_labels = None
depends_on = None


def upgrade():
    event_payload = sa.column("payload", sa.JSON())
    op.create_index(
        "events_discussion_topic_sequence",
        "events",
        ["project_id", "kind", "aggregate_id", "sequence"],
    )
    op.create_index(
        "events_discussion_experiment_sequence",
        "events",
        ["project_id", "kind", event_payload["experiment_id"].as_string(), "sequence"],
    )
    record_payload = sa.column("payload", sa.JSON())
    op.create_index(
        "records_discussion_reader",
        "records",
        [
            "project_id",
            "kind",
            record_payload["experiment_id"].as_string(),
            record_payload["reader_key"].as_string(),
        ],
        sqlite_where=sa.text("kind = 'discussion_reader'"),
        postgresql_where=sa.text("kind = 'discussion_reader'"),
    )
    op.create_index(
        "records_discussion_subscription",
        "records",
        [
            "project_id",
            "kind",
            record_payload["experiment_id"].as_string(),
            record_payload["reader_key"].as_string(),
            record_payload["topic_id"].as_string(),
        ],
        sqlite_where=sa.text("kind = 'discussion_subscription'"),
        postgresql_where=sa.text("kind = 'discussion_subscription'"),
    )


def downgrade():
    op.drop_index("records_discussion_subscription", table_name="records")
    op.drop_index("records_discussion_reader", table_name="records")
    op.drop_index("events_discussion_experiment_sequence", table_name="events")
    op.drop_index("events_discussion_topic_sequence", table_name="events")
