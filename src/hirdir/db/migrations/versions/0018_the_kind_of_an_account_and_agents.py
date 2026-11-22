"""the kind of an account, and agents

Revision: 0018
Revises: 0017

An account is a person's, a service's or an agent's (P-316): `users.kind`, `person`,
`service` or `agent`, takes the place of `users.is_service_account`, which is dropped.
Every service account is `service`, and every other account `person`: there is no agent
before this release. `users.answerable_hid`, an agent's alone, names the person
answerable for it, and is empty for every account here. `audit_events.for_hid` holds,
for an event made by an agent, the person it was answerable to then; it is empty for
every event here, since no agent made any. Two indexes of `audit_events` are added, by
`actor_hid` and by `for_hid`, so that the events of one account, of the accounts of one
kind and those made for one person are found without reading the whole trail.

No other value of a row is changed and no event is written: the kind of each account is
what it was, in another word.
"""

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as users:
        users.add_column(sa.Column("kind", sa.String(10), nullable=False, server_default="person"))
        users.add_column(sa.Column("answerable_hid", sa.String(36)))
    accounts = sa.table(
        "users", sa.column("kind", sa.String), sa.column("is_service_account", sa.Boolean)
    )
    op.execute(
        accounts.update().where(accounts.c.is_service_account.is_(True)).values(kind="service")
    )
    with op.batch_alter_table("users") as users:
        users.drop_column("is_service_account")
        users.create_foreign_key("fk_users_answerable_hid", "users", ["answerable_hid"], ["hid"])
        users.create_index("ix_users_answerable_hid", ["answerable_hid"], unique=False)
    with op.batch_alter_table("audit_events") as events:
        events.add_column(sa.Column("for_hid", sa.String(36)))
        events.create_index("audit_events_actor", ["actor_hid"], unique=False)
        events.create_index("audit_events_for", ["for_hid"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("audit_events") as events:
        events.drop_index("audit_events_for")
        events.drop_index("audit_events_actor")
        events.drop_column("for_hid")
    with op.batch_alter_table("users") as users:
        users.drop_index("ix_users_answerable_hid")
        users.drop_constraint("fk_users_answerable_hid", type_="foreignkey")
        users.add_column(
            sa.Column("is_service_account", sa.Boolean, nullable=False, server_default=sa.false())
        )
    accounts = sa.table(
        "users", sa.column("kind", sa.String), sa.column("is_service_account", sa.Boolean)
    )
    # An agent holds tokens, as a service account does: before this release it is one.
    op.execute(accounts.update().where(accounts.c.kind != "person").values(is_service_account=True))
    with op.batch_alter_table("users") as users:
        users.drop_column("answerable_hid")
        users.drop_column("kind")
