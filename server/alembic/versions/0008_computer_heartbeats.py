"""Store the latest live snapshot for each computer.

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "computer_heartbeats",
        sa.Column("computer_id", sa.Integer(), sa.ForeignKey("computers.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sampled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("login", sa.String(300), nullable=True),
        sa.Column("login_key", sa.Text(), nullable=True),
        sa.Column("process_name", sa.String(260), nullable=True),
        sa.Column("window_title", sa.String(1024), nullable=True),
        sa.Column("last_input_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_idle", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("computer_heartbeats")
