"""Persist daily activity totals and pending UTC date ranges.

Revision ID: 0007
Revises: 0006
"""

from datetime import UTC, timedelta

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "daily_totals",
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("first_activity_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_seconds", sa.Integer(), nullable=False),
        sa.Column("active_seconds", sa.Integer(), nullable=False),
        sa.Column("idle_seconds", sa.Integer(), nullable=False),
        sa.Column("late_seconds", sa.Integer(), nullable=False),
        sa.Column("early_departure_seconds", sa.Integer(), nullable=False),
        sa.Column("overtime_seconds", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_daily_totals_day", "daily_totals", ["day"])
    pending = op.create_table(
        "daily_totals_pending",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("next_day", sa.Date(), nullable=False),
        sa.Column("last_day", sa.Date(), nullable=False),
    )
    op.create_index("ix_daily_totals_pending_next_day", "daily_totals_pending", ["next_day"])

    # Have the worker backfill existing spans a few dates at a time.
    spans = sa.table(
        "activity_spans", sa.column("started_at", sa.DateTime(timezone=True)),
        sa.column("ended_at", sa.DateTime(timezone=True)),
    )
    first, end = op.get_bind().execute(sa.select(
        sa.func.min(spans.c.started_at), sa.func.max(spans.c.ended_at),
    )).one()
    if first is not None and end is not None and end > first:
        first = first.astimezone(UTC) if first.tzinfo is not None else first
        end = end.astimezone(UTC) if end.tzinfo is not None else end
        op.bulk_insert(pending, [{"next_day": first.date(), "last_day": (end - timedelta(microseconds=1)).date()}])


def downgrade() -> None:
    op.drop_index("ix_daily_totals_pending_next_day", table_name="daily_totals_pending")
    op.drop_table("daily_totals_pending")
    op.drop_index("ix_daily_totals_day", table_name="daily_totals")
    op.drop_table("daily_totals")
