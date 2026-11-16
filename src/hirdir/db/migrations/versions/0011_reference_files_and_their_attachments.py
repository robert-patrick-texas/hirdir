"""reference files and their attachments

Revision: 0011
Revises: 0010

References, in `reference_files`: a file kept by hirdir, whose content is kept beside
the database under its checksum and never in it, or a link to one kept elsewhere, each
with a title and a kind (P-158). A reference is on one record or more, a catalog entry,
a region, a site, a location, a circuit or an item, through `reference_attachments`.
Loads the `reference_kind` list with its defaults, written out here so that the
migration does not change with the code.

Nothing that is held changes: there is no reference until somebody adds one, and the
setting of the kinds of file taken is at its default until an Admin changes it.
"""

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

REFERENCE_KINDS = [
    ("photograph", "Photograph"),
    ("map", "Map"),
    ("sketch", "Sketch"),
    ("floor_plan", "Floor plan"),
    ("diagram", "Diagram"),
    ("administration_guide", "Administration guide"),
    ("installation_guide", "Installation guide"),
    ("data_sheet", "Data sheet"),
    ("release_notes", "Release notes"),
    ("letter_of_authorization", "Letter of authorization"),
    ("test_results", "Test results"),
    ("other", "Other"),
]
ATTACHABLE = (
    ("catalog_entry_hid", "catalog_entries"),
    ("region_hid", "regions"),
    ("site_hid", "sites"),
    ("location_hid", "locations"),
    ("circuit_hid", "circuits"),
    ("item_hid", "items"),
)


def _bookkeeping() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(36)),
        sa.Column("updated_by", sa.String(36)),
        sa.Column("row_version", sa.Integer, nullable=False),
    ]


def _load_defaults(list_name: str, values: list[tuple[str, str]]) -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
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


def upgrade() -> None:
    op.create_table(
        "reference_files",
        sa.Column("hid", sa.String(36), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("notes", sa.Text),
        sa.Column("url", sa.String(2000)),
        sa.Column("file_name", sa.String(255)),
        sa.Column("media_type", sa.String(100)),
        sa.Column("size_bytes", sa.BigInteger),
        sa.Column("sha256", sa.String(64)),
        *_bookkeeping(),
        sa.CheckConstraint(
            "(url IS NULL) <> (sha256 IS NULL)", name="reference_files_file_or_link"
        ),
        sa.CheckConstraint(
            "(sha256 IS NULL) = (file_name IS NULL) AND (sha256 IS NULL) = (size_bytes IS NULL)"
            " AND (sha256 IS NULL) = (media_type IS NULL)",
            name="reference_files_whole_file",
        ),
    )
    op.create_index("ix_reference_files_sha256", "reference_files", ["sha256"])
    op.create_table(
        "reference_attachments",
        sa.Column("hid", sa.String(36), primary_key=True),
        sa.Column(
            "reference_file_hid",
            sa.String(36),
            sa.ForeignKey("reference_files.hid"),
            nullable=False,
        ),
        *(
            sa.Column(column, sa.String(36), sa.ForeignKey(f"{table}.hid"))
            for column, table in ATTACHABLE
        ),
        *_bookkeeping(),
        sa.CheckConstraint(
            " + ".join(
                f"(CASE WHEN {column} IS NULL THEN 0 ELSE 1 END)" for column, _ in ATTACHABLE
            )
            + " = 1",
            name="reference_attachments_one_record",
        ),
        *(
            sa.UniqueConstraint(
                "reference_file_hid", column, name=f"reference_attachments_{column}_once"
            )
            for column, _ in ATTACHABLE
        ),
    )
    for column in ("reference_file_hid", *(column for column, _ in ATTACHABLE)):
        op.create_index(f"ix_reference_attachments_{column}", "reference_attachments", [column])
    _load_defaults("reference_kind", REFERENCE_KINDS)


def downgrade() -> None:
    choices = sa.table("choices", sa.column("list", sa.String))
    op.execute(choices.delete().where(choices.c.list == "reference_kind"))
    op.drop_table("reference_attachments")
    op.drop_table("reference_files")
