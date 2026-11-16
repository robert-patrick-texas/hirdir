"""The shapes of references in the API: a file kept by hirdir or a link to one kept
elsewhere, the records it is on, and a reference as a record lists it (P-158 to P-162)."""

from datetime import datetime
from typing import Literal

from pydantic import Field

from hirdir.api.records import Hid, LongText, Name
from hirdir.api.schemas import Model

ReferenceForm = Literal["file", "link"]
HolderKind = Literal["catalog_entry", "region", "site", "location", "circuit", "item"]
ReferenceSource = Literal["own", "catalog", "location", "site", "region"]


class ReferenceRecord(Model):
    """A record a reference is on."""

    hid: str = Field(description="The attachment: what is taken off.")
    record_type: HolderKind
    record_hid: str
    label: str = Field(
        description="How the record is named: a place by its path, a model by its vendor "
        "and PID, a circuit by its enterprise circuit ID or name, an item by its host name, "
        "name, asset tag or serial number."
    )


class ReferenceFileOut(Model):
    """A reference: a file kept by hirdir, or a link to one kept elsewhere."""

    hid: str
    title: str
    kind: str = Field(description="A value of the `reference_kind` list.")
    form: ReferenceForm = Field(description="`file`, kept by hirdir, or `link`.")
    notes: str | None
    url: str | None = Field(description="The address of a link. Blank on a file.")
    file_name: str | None = Field(description="The name a file was uploaded with.")
    media_type: str | None = Field(
        description="What a file is served as, from its extension: `application/pdf`, "
        "`image/jpeg`, and `application/octet-stream` for an extension an Admin added."
    )
    size_bytes: int | None
    sha256: str | None = Field(description="The SHA-256 checksum of a file's content.")
    shown_in_page: bool = Field(
        description="A JPEG, PNG, GIF or WebP picture, which the web UI shows in the page. "
        "Every other file is downloaded."
    )
    content_missing: bool = Field(
        description="True only after a restore that was told to go on without the content "
        "of this file: a download of it is a 404."
    )
    attachments: list[ReferenceRecord] = Field(description="The records it is on.")
    attachment_count: int
    row_version: int
    created_at: datetime
    created_by: str | None
    created_by_name: str | None = Field(description="The username of whoever added it.")
    updated_at: datetime
    updated_by: str | None
    updated_by_name: str | None = Field(description="The username of whoever changed it last.")


class ListedReference(ReferenceFileOut):
    """A reference as a record lists it: its own, or one it has from a record it stands
    under, nearest first."""

    attachment_hid: str = Field(description="The attachment it is listed by.")
    source: ReferenceSource = Field(
        description="`own`, attached to this record; `catalog`, to an item's model; "
        "`location`, `site` or `region`, to a place it is in or at."
    )
    source_hid: str = Field(description="The record it is attached to.")
    source_label: str = Field(description="That record's path or name.")


class ReferenceLinkNew(Model):
    """A link to a file kept elsewhere, to put on one record or more."""

    title: Name
    kind: str = Field(max_length=40, description="A value of the `reference_kind` list.")
    url: str = Field(max_length=2000, description="`https://` or `http://`, with no space.")
    notes: LongText | None = None
    attach_to: list[Hid] = Field(
        min_length=1,
        max_length=1000,
        description="The records it goes on: catalog entries, regions, sites, locations, "
        "circuits or items.",
    )


class ReferencePatch(Model):
    """What to change of a reference. A field left out is left alone."""

    row_version: int
    title: Name | None = None
    kind: str | None = Field(default=None, max_length=40)
    notes: LongText | None = None
    url: str | None = Field(
        default=None, max_length=2000, description="The address of a link. A file has none."
    )


class ReferenceAttach(Model):
    """More records to put a reference on."""

    records: list[Hid] = Field(min_length=1, max_length=1000)


class Detached(Model):
    """What taking a reference off a record did."""

    erased: bool = Field(
        description="True where that was the last record it was on: it was erased, and "
        "its content with it unless another reference holds the same."
    )
