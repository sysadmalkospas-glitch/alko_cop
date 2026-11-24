"""Add reusable work schedules and optional group and employee assignments.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "work_schedules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False, unique=True),
        sa.Column("pattern", sa.JSON(), nullable=False),
        sa.Column("late_tolerance_minutes", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "late_tolerance_minutes BETWEEN 0 AND 1440",
            name="ck_work_schedules_late_tolerance_minutes",
        ),
    )
    for table in ("groups", "employees"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("schedule_id", sa.Integer(), nullable=True))
            batch.create_foreign_key(f"fk_{table}_schedule_id", "work_schedules", ["schedule_id"], ["id"])
            batch.create_index(f"ix_{table}_schedule_id", ["schedule_id"])


def downgrade() -> None:
    for table in ("employees", "groups"):
        with op.batch_alter_table(table) as batch:
            batch.drop_index(f"ix_{table}_schedule_id")
            batch.drop_constraint(f"fk_{table}_schedule_id", type_="foreignkey")
            batch.drop_column("schedule_id")
    op.drop_table("work_schedules")
