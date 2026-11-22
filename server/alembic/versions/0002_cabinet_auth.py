"""Cabinet users, sessions and login throttling.

Revision ID: 0002
Revises: 0001
"""

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cabinet_users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("login", sa.String(128), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("login"),
    )
    op.create_table(
        "cabinet_sessions",
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["cabinet_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("token_hash"),
    )
    op.create_index("ix_cabinet_sessions_user_id", "cabinet_sessions", ["user_id"])
    op.create_index("ix_cabinet_sessions_expires_at", "cabinet_sessions", ["expires_at"])
    op.create_table(
        "login_throttles",
        sa.Column("key", sa.String(70), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("window_ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_index("ix_login_throttles_window_ends_at", "login_throttles", ["window_ends_at"])


def downgrade() -> None:
    op.drop_table("login_throttles")
    op.drop_table("cabinet_sessions")
    op.drop_table("cabinet_users")
