"""Backfill observed Windows logins and use case-insensitive binding keys.

Revision ID: 0004
Revises: 0003
"""

from alembic import context, op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def _backfill_bindings(db, bindings) -> None:
    retained = {}
    duplicates = []
    for row in db.execute(sa.select(bindings.c.id, bindings.c.employee_id, bindings.c.login).order_by(bindings.c.id)):
        key = row.login.casefold()
        if key not in retained:
            retained[key] = row
        elif retained[key].employee_id == row.employee_id:
            duplicates.append({"binding_id": row.id})
        else:
            raise RuntimeError(
                f"Employee login bindings {retained[key].id} and {row.id} match ignoring case "
                "but reference different employees. Resolve the conflicting bindings before upgrading."
            )

    op.add_column("employee_logins", sa.Column("login_key", sa.Text(), nullable=True))
    if duplicates:
        db.execute(bindings.delete().where(bindings.c.id == sa.bindparam("binding_id")), duplicates)
    if retained:
        db.execute(
            bindings.update().where(bindings.c.id == sa.bindparam("binding_id")),
            [{"binding_id": row.id, "login_key": key} for key, row in retained.items()],
        )
    with op.batch_alter_table("employee_logins") as batch:
        batch.alter_column("login_key", existing_type=sa.Text(), nullable=False)
        batch.create_unique_constraint("uq_employee_logins_login_key", ["login_key"])


def _historical_sightings(db):
    sources = [
        ("activity_spans", "started_at", "ended_at"),
        ("system_events", "occurred_at", "occurred_at"),
        ("screenshots", "taken_at", "taken_at"),
    ]
    for table, first, last in sources:
        columns = [sa.column(first, sa.DateTime(timezone=True))]
        if first != last:
            columns.append(sa.column(last, sa.DateTime(timezone=True)))
        source = sa.table(table, sa.column("login"), sa.column("computer_id"), *columns)
        # Reduce historical rows by login and computer before transferring them.
        statement = sa.select(
            source.c.login, source.c.computer_id,
            sa.func.min(source.c[first]).label("first_seen_at"),
            sa.func.max(source.c[last]).label("last_seen_at"),
        ).where(source.c.login.is_not(None)).group_by(source.c.login, source.c.computer_id)
        with db.execute(statement) as rows:
            yield from rows


def _backfill_observations(db, observed) -> None:
    sightings = {}
    for row in _historical_sightings(db):
        if not row.login.strip():
            continue
        key = row.login.casefold()
        if key not in sightings:
            sightings[key] = {
                "login_key": key, "login": row.login,
                "first_seen_at": row.first_seen_at, "last_seen_at": row.last_seen_at,
                "last_computer_id": row.computer_id,
            }
            continue

        saved = sightings[key]
        saved["first_seen_at"] = min(saved["first_seen_at"], row.first_seen_at)
        if (row.last_seen_at, row.computer_id, row.login) > (
            saved["last_seen_at"], saved["last_computer_id"], saved["login"],
        ):
            saved.update(login=row.login, last_seen_at=row.last_seen_at, last_computer_id=row.computer_id)
    if sightings:
        db.execute(observed.insert(), list(sightings.values()))


def upgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("Revision 0004 requires an online database to backfill Windows login keys.")
    db = op.get_bind()
    bindings = sa.table(
        "employee_logins", sa.column("id"), sa.column("employee_id"),
        sa.column("login"), sa.column("login_key", sa.Text()),
    )
    _backfill_bindings(db, bindings)
    observed = op.create_table(
        "observed_logins",
        sa.Column("login_key", sa.Text(), primary_key=True),
        sa.Column("login", sa.String(300), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_computer_id", sa.Integer(), sa.ForeignKey("computers.id", ondelete="SET NULL")),
    )
    _backfill_observations(db, observed)


def downgrade() -> None:
    op.drop_table("observed_logins")
    with op.batch_alter_table("employee_logins") as batch:
        batch.drop_constraint("uq_employee_logins_login_key", type_="unique")
        batch.drop_column("login_key")
