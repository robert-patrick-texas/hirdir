"""people are contacts, and the kinds of external system a list

Revision: 0012
Revises: 0011

Every person is a contact, and a user is a part that a contact plays (P-172): a user
gains `contact_hid` and loses `display_name` and `email`, which are its contact's from
now on. Each user that is no service account and has a display name or an email is
given a contact: the one that has its email already, where there is one and it is no
other user's, which is left as it is; with no email, the one of its display name, as a
file finds a contact by name; or else a new one with the user's display name, or its
username where it has none, and its email where a contact takes it. Users that may
sign in go first, then the disabled, each by username. Each user that had a display
name or an email has an audit event by `system` that keeps what was dropped, and the
contact it was given; a contact made has one, and a contact given to a user one more.
A service account keeps no display name. Contacts gain `phone2`, a second number, and
the kind of an external system takes 40 characters.

Loads the `system_kind` list with the eight kinds of external system that were fixed
until now (P-170), written out here so that the migration does not change with the
code. Every system keeps its kind, as each is one of them.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

SYSTEM_KINDS = [
    ("monitoring", "Monitoring"),
    ("config_backup", "Configuration backup"),
    ("access_control", "Access control"),
    ("sdn_controller", "SDN controller"),
    ("cloud_service", "Cloud service"),
    ("dns", "DNS"),
    ("discovery", "Discovery"),
    ("other", "Other"),
]


def _key(text: str) -> str:
    return text.strip().casefold()


def _load_defaults(list_name: str, values: list[tuple[str, str]], now: datetime) -> None:
    choices = sa.table(
        "choices",
        sa.column("hid", sa.String),
        sa.column("list", sa.String),
        sa.column("value", sa.String),
        sa.column("value_key", sa.String),
        sa.column("label", sa.String),
        sa.column("sort", sa.Integer),
        sa.column("active", sa.Boolean),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
        sa.column("row_version", sa.Integer),
    )
    there = set(
        op.get_bind()
        .execute(sa.select(choices.c.value_key).where(choices.c.list == list_name))
        .scalars()
    )
    # A site may have entered values of its own already: those are left as they are.
    op.bulk_insert(
        choices,
        [
            {
                "hid": str(uuid.uuid7()),
                "list": list_name,
                "value": value,
                "value_key": value.casefold(),
                "label": label,
                "sort": (place + 1) * 10,
                "active": True,
                "created_at": now,
                "updated_at": now,
                "row_version": 1,
            }
            for place, (value, label) in enumerate(values)
            if value.casefold() not in there
        ],
    )


def _audit(now: datetime) -> Any:
    return sa.table(
        "audit_events",
        sa.column("hid", sa.String),
        sa.column("at", sa.DateTime),
        sa.column("actor_hid", sa.String),
        sa.column("via", sa.String),
        sa.column("request_id", sa.String),
        sa.column("action", sa.String),
        sa.column("record_type", sa.String),
        sa.column("record_hid", sa.String),
        sa.column("changes", sa.JSON),
    )


def _is_address(email: str) -> bool:
    """Say whether a contact takes email, as the contacts of 0.9.3 check it: name@host."""
    local, at, domain = email.partition("@")
    return bool(local and at and domain) and " " not in email and "@" not in domain


def _named(by_name: dict[str, list[tuple[str, str | None]]], name: str) -> str | None:
    """Return the contact a user with no email is, by its display name, as a file finds a
    contact by its name: the one contact of that name, or of several the one with no
    email. None where there is none, or no one answers."""
    if not name:
        return None
    named = by_name.get(_key(name), [])
    if len(named) == 1:
        return named[0][0]
    bare = [hid for hid, email in named if email is None]
    return bare[0] if len(bare) == 1 else None


def _give_users_their_contacts(now: datetime) -> None:
    bind = op.get_bind()
    users = sa.table(
        "users",
        sa.column("hid", sa.String),
        sa.column("username", sa.String),
        sa.column("username_key", sa.String),
        sa.column("display_name", sa.String),
        sa.column("email", sa.String),
        sa.column("is_service_account", sa.Boolean),
        sa.column("disabled", sa.Boolean),
        sa.column("contact_hid", sa.String),
        sa.column("updated_at", sa.DateTime),
        sa.column("row_version", sa.Integer),
    )
    contacts = sa.table(
        "contacts",
        sa.column("hid", sa.String),
        sa.column("name", sa.String),
        sa.column("name_key", sa.String),
        sa.column("email", sa.String),
        sa.column("email_key", sa.String),
        sa.column("record_status", sa.String),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
        sa.column("row_version", sa.Integer),
    )
    audit = _audit(now)
    by_email: dict[str, str] = {}
    by_name: dict[str, list[tuple[str, str | None]]] = {}
    for row in bind.execute(sa.select(contacts.c.hid, contacts.c.name_key, contacts.c.email_key)):
        if row.email_key is not None:
            by_email[row.email_key] = row.hid
        by_name.setdefault(row.name_key, []).append((row.hid, row.email_key))
    taken: set[str] = set()
    events: list[dict[str, Any]] = []
    # A user that may sign in is given a contact before one that is disabled, and of
    # those alike the first by username: a contact is one user's at most.
    everyone = bind.execute(
        sa.select(
            users.c.hid,
            users.c.username,
            users.c.display_name,
            users.c.email,
            users.c.is_service_account,
        ).order_by(users.c.disabled, users.c.username_key)
    ).all()
    for user in everyone:
        name = (user.display_name or "").strip()
        email = (user.email or "").strip()
        # What is dropped from the user is in its event, so the trail keeps what it was.
        changes = [
            {"field": field, "old": value, "new": None}
            for field, value in (("display_name", name), ("email", email))
            if value
        ]
        found = None
        if not user.is_service_account and (name or email):
            address = email if email and _is_address(email) else None
            if address and _key(address) in by_email:
                # A contact is one user's at most: the second user of one email has none.
                match = by_email[_key(address)]
                found = match if match not in taken else None
            else:
                # With no email, the contact of its name, as a file finds one by name; where
                # there is none, or it is another user's, a contact of its own is made.
                match = None if address else _named(by_name, name)
                if match is not None and match not in taken:
                    found = match
                else:
                    found = str(uuid.uuid7())
                    made = {"name": name or user.username, "email": address}
                    bind.execute(
                        contacts.insert().values(
                            hid=found,
                            name=made["name"],
                            name_key=_key(made["name"]),
                            email=address,
                            email_key=_key(address) if address else None,
                            record_status="active",
                            created_at=now,
                            updated_at=now,
                            row_version=1,
                        )
                    )
                    if address:
                        by_email[_key(address)] = found
                    by_name.setdefault(_key(made["name"]), []).append((found, address))
                    made_changes = [
                        {"field": field, "old": None, "new": value}
                        for field, value in (*made.items(), ("record_status", "active"))
                        if value is not None
                    ]
                    events.append(_event(now, "create", "contact", found, made_changes))
        if found is not None:
            taken.add(found)
            changes.append({"field": "contact_hid", "old": None, "new": found})
            link = {"field": "user_hid", "old": None, "new": user.hid}
            events.append(_event(now, "update", "contact", found, [link]))
        if not changes:
            continue
        if found is not None:
            bind.execute(
                users.update()
                .where(users.c.hid == user.hid)
                .values(contact_hid=found, updated_at=now, row_version=users.c.row_version + 1)
            )
        events.append(_event(now, "update", "user", user.hid, changes))
    if events:
        op.bulk_insert(audit, events)


def _event(
    now: datetime, action: str, record_type: str, hid: str, changes: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "hid": str(uuid.uuid7()),
        "at": now,
        "actor_hid": None,
        "via": "system",
        "request_id": "upgrade-0012",
        "action": action,
        "record_type": record_type,
        "record_hid": hid,
        "changes": changes,
    }


def upgrade() -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
    with op.batch_alter_table("contacts") as contacts:
        contacts.add_column(sa.Column("phone2", sa.String(50)))
    with op.batch_alter_table("users") as users:
        users.add_column(sa.Column("contact_hid", sa.String(36)))
        users.create_foreign_key("fk_users_contact_hid", "contacts", ["contact_hid"], ["hid"])
        users.create_unique_constraint("users_contact", ["contact_hid"])
    _give_users_their_contacts(now)
    with op.batch_alter_table("users") as users:
        users.drop_column("display_name")
        users.drop_column("email")
    # A kind is a value of a list now, which may be as long as any other value of one.
    with op.batch_alter_table("external_systems") as systems:
        systems.alter_column("kind", type_=sa.String(40), existing_type=sa.String(20))
    _load_defaults("system_kind", SYSTEM_KINDS, now)


def downgrade() -> None:
    choices = sa.table("choices", sa.column("list", sa.String))
    op.execute(choices.delete().where(choices.c.list == "system_kind"))
    with op.batch_alter_table("external_systems") as systems:
        systems.alter_column("kind", type_=sa.String(20), existing_type=sa.String(40))
    with op.batch_alter_table("users") as users:
        users.add_column(
            sa.Column("display_name", sa.String(200), nullable=False, server_default="")
        )
        users.add_column(sa.Column("email", sa.String(254), nullable=False, server_default=""))
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE users SET"
            " display_name = COALESCE((SELECT name FROM contacts"
            " WHERE contacts.hid = users.contact_hid), ''),"
            " email = COALESCE((SELECT email FROM contacts"
            " WHERE contacts.hid = users.contact_hid), '')"
        )
    )
    with op.batch_alter_table("users") as users:
        users.drop_constraint("users_contact", type_="unique")
        users.drop_constraint("fk_users_contact_hid", type_="foreignkey")
        users.drop_column("contact_hid")
    with op.batch_alter_table("contacts") as contacts:
        contacts.drop_column("phone2")
