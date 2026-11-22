"""Initial schema based on the existing server models.

Revision ID: 0001
Revises:
"""

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "offices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "monitoring_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("idle_threshold_sec", sa.Integer(), nullable=False),
        sa.Column("screenshots_enabled", sa.Boolean(), nullable=False),
        sa.Column("screenshot_interval_sec", sa.Integer(), nullable=False),
        sa.Column("screenshot_quality", sa.Integer(), nullable=False),
        sa.Column("screenshot_format", sa.String(16), nullable=False),
        sa.Column("screenshot_max_width", sa.Integer(), nullable=False),
        sa.Column("screenshot_skip_unchanged", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "groups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("office_id", sa.Integer(), nullable=True),
        sa.Column("profile_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["office_id"], ["offices.id"]),
        sa.ForeignKeyConstraint(["profile_id"], ["monitoring_profiles.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "employees",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("full_name", sa.String(300), nullable=False),
        sa.Column("position", sa.String(200), nullable=True),
        sa.Column("group_id", sa.Integer(), nullable=True),
        sa.Column("is_dismissed", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "employee_logins",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("login", sa.String(300), nullable=False),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("login"),
    )
    op.create_table(
        "computers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("machine_id", sa.String(64), nullable=False),
        sa.Column("hostname", sa.String(255), nullable=False),
        sa.Column("os_version", sa.String(255), nullable=True),
        sa.Column("agent_version", sa.String(64), nullable=True),
        sa.Column("office_id", sa.Integer(), nullable=True),
        sa.Column("profile_id", sa.Integer(), nullable=True),
        sa.Column("token_hash", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["office_id"], ["offices.id"]),
        sa.ForeignKeyConstraint(["profile_id"], ["monitoring_profiles.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("machine_id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_table(
        "activity_spans",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("computer_id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.String(64), nullable=False),
        sa.Column("login", sa.String(300), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_idle", sa.Boolean(), nullable=False),
        sa.Column("process_name", sa.String(260), nullable=True),
        sa.Column("window_title", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["computer_id"], ["computers.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("computer_id", "client_id"),
    )
    op.create_index("ix_activity_spans_computer_id", "activity_spans", ["computer_id"])
    op.create_index("ix_activity_spans_login", "activity_spans", ["login"])
    op.create_index("ix_activity_spans_started_at", "activity_spans", ["started_at"])
    op.create_table(
        "system_events",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("computer_id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.String(64), nullable=False),
        sa.Column("login", sa.String(300), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["computer_id"], ["computers.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("computer_id", "client_id"),
    )
    op.create_index("ix_system_events_computer_id", "system_events", ["computer_id"])
    op.create_index("ix_system_events_occurred_at", "system_events", ["occurred_at"])
    op.create_table(
        "screenshots",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("computer_id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.String(64), nullable=False),
        sa.Column("login", sa.String(300), nullable=False),
        sa.Column("taken_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("monitor", sa.Integer(), nullable=False),
        sa.Column("file_path", sa.String(500), nullable=False),
        sa.Column("content_type", sa.String(32), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["computer_id"], ["computers.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("computer_id", "client_id"),
    )
    op.create_index("ix_screenshots_computer_id", "screenshots", ["computer_id"])
    op.create_index("ix_screenshots_taken_at", "screenshots", ["taken_at"])


def downgrade() -> None:
    op.drop_table("screenshots")
    op.drop_table("system_events")
    op.drop_table("activity_spans")
    op.drop_table("computers")
    op.drop_table("employee_logins")
    op.drop_table("employees")
    op.drop_table("groups")
    op.drop_table("monitoring_profiles")
    op.drop_table("offices")
