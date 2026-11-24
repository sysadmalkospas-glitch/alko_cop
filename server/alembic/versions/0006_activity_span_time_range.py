"""Index activity spans by the time range they overlap.

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_context().dialect.name == "postgresql":
        op.create_index(
            "ix_activity_spans_time_range", "activity_spans",
            [sa.text("tstzrange(started_at, greatest(started_at, ended_at), '[]')")],
            postgresql_using="gist",
        )


def downgrade() -> None:
    if op.get_context().dialect.name == "postgresql":
        op.drop_index("ix_activity_spans_time_range", table_name="activity_spans")
