"""Normalize employee positions and add cabinet names for computers.

Revision ID: 0003
Revises: 0002
"""

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "positions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False, unique=True),
    )
    op.add_column("employees", sa.Column("position_id", sa.Integer(), nullable=True))
    op.execute(
        "INSERT INTO positions (name) SELECT DISTINCT position FROM employees WHERE position IS NOT NULL"
    )
    op.execute(
        "UPDATE employees SET position_id = (SELECT id FROM positions WHERE name = employees.position)"
    )
    with op.batch_alter_table("employees") as batch:
        batch.create_foreign_key("fk_employees_position_id", "positions", ["position_id"], ["id"])
        batch.drop_column("position")
        batch.create_index("ix_employees_position_id", ["position_id"])
    op.add_column("computers", sa.Column("display_name", sa.String(255), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("computers") as batch:
        batch.drop_column("display_name")
    op.add_column("employees", sa.Column("position", sa.String(200), nullable=True))
    op.execute("UPDATE employees SET position = (SELECT name FROM positions WHERE id = employees.position_id)")
    with op.batch_alter_table("employees") as batch:
        batch.drop_index("ix_employees_position_id")
        batch.drop_constraint("fk_employees_position_id", type_="foreignkey")
        batch.drop_column("position_id")
    op.drop_table("positions")
