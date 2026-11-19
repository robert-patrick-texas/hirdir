"""The shapes of requests and responses. These, as OpenAPI, are the contract."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Model(BaseModel):
    """The base of every schema: built from records, unknown fields refused."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")


class Page[T](Model):
    """One page of a list."""

    items: list[T]
    total: int
    limit: int
    offset: int


class ProblemField(Model):
    """What is wrong with one field of a request."""

    field: str
    message: str


class ProblemRecord(Model):
    """The record that already has the value a change was refused for (P-207)."""

    hid: str
    record_type: str = Field(
        description="Its kind, as the audit trail names it: `item`, `catalog_entry`, `vendor`."
    )
    label: str = Field(
        description="What it is known by: an item by its host name, name, asset tag or "
        "serial number, a model by its vendor and PID, any other by its name or label."
    )


class ProblemDeleted(Model):
    """The deletion of a record that a request named, read from the audit trail (P-236)."""

    at: datetime = Field(description="When it was deleted.")
    actor_hid: str | None = Field(description="Who deleted it.")
    actor_name: str | None = Field(description="The username of who deleted it.")
    reason: str | None = Field(description="Why, as the Admin gave it.")


class ProblemBusy(Model):
    """Why a server past its ceiling did not take a request (P-265)."""

    state: Literal["busy", "very_busy"] = Field(
        description="`busy`: what is long by nature, a report, an export or a preview, "
        "is not taken. `very_busy`: no read of the API is."
    )
    because: list[Literal["response_ms", "cpu_percent"]] = Field(
        description="The measures that are past the ceiling: how long requests take, the "
        "processor time the process uses as a percentage of one processor."
    )
    retry_after: int = Field(description="The seconds to wait, as `Retry-After` says.")


class Problem(Model):
    """An error, as an RFC 9457 problem document."""

    type: str = "about:blank"
    title: str
    status: int
    detail: str = ""
    errors: list[ProblemField] = []
    existing: ProblemRecord | None = Field(
        default=None,
        description="On a 409 for a value another record has, such as a serial number, an "
        "asset tag, a PID or a name: that record. Left out of every other problem.",
    )
    deleted: ProblemDeleted | None = Field(
        default=None,
        description="On a 404 for an item or a device group that an Admin deleted: when, "
        "by whom and why. Left out of every other problem.",
    )
    depends_on: list[ProblemRecord] | None = Field(
        default=None,
        description="On a 409 for a record that others stand on, as a stack or a cluster "
        "that items run on is refused retirement: those records, each as `existing` names "
        "one (P-247). Left out of every other problem.",
    )
    busy: ProblemBusy | None = Field(
        default=None,
        description="On the 503 of a server that is past its ceiling and took nothing of "
        "the request (P-265). Left out of every other problem, the 503 of a change that "
        "waited for another to be stored among them.",
    )


class GroupRef(Model):
    """A user group, as named on a user."""

    hid: str
    name: str


class PersonRef(Model):
    """The contact a user is: its name, email and numbers, read when the user is read."""

    hid: str
    name: str
    email: str | None
    phone: str | None
    phone2: str | None
    record_status: str


class UserOut(Model):
    """A user: the part of a person who signs in, or a service account (P-172)."""

    hid: str
    username: str
    contact_hid: str | None
    contact: PersonRef | None = Field(
        description="The contact the user is. None for a service account, or a user not given one."
    )
    display_name: str = Field(description="The name of its contact; blank where it has none.")
    email: str = Field(description="The email of its contact; blank where it has none.")
    is_service_account: bool
    disabled: bool
    role: str | None = Field(description="The highest role held directly or through a group.")
    groups: list[GroupRef]
    last_sign_in_at: datetime | None
    row_version: int
    created_at: datetime
    updated_at: datetime


class NewPerson(Model):
    """A new contact, made with the user that it is."""

    name: str = Field(min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=254)
    organization: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=50)
    phone2: str | None = Field(default=None, max_length=50)


class UserCreate(Model):
    """A new user. The person is a contact: one there is, a new one, or none yet."""

    username: str = Field(
        min_length=1,
        max_length=64,
        description="What the person signs in with. An Admin can change it later.",
    )
    contact_hid: str | None = Field(
        default=None, max_length=36, description="The contact the user is."
    )
    contact: NewPerson | None = Field(
        default=None, description="A new contact, made in the same change."
    )
    is_service_account: bool = False
    access_code: str | None = Field(
        default=None, max_length=200, description="Left out, a code is generated."
    )
    role: str | None = Field(default=None, description="A role to grant at once.")


class UserCreated(Model):
    """A user just created, with the access code that is shown this once."""

    user: UserOut
    access_code: str | None


class UserPatch(Model):
    """Fields of a user to change, and the version they were read at."""

    row_version: int
    username: str | None = Field(
        default=None, min_length=1, max_length=64, description="Another username (P-173)."
    )
    contact_hid: str | None = Field(
        default=None,
        max_length=36,
        description="Another contact; null for none. A service account has none.",
    )
    disabled: bool | None = None


class AccessCodeSet(Model):
    """A new access code for a user. Left out, a code is generated."""

    access_code: str | None = Field(default=None, max_length=200)


class AccessCodeOut(Model):
    """The access code just set, shown this once."""

    access_code: str


class SignIn(Model):
    """A username and access code."""

    username: str = Field(min_length=1, max_length=64)
    access_code: str = Field(min_length=1, max_length=200)


class SessionOut(Model):
    """A session: the token to send as `Authorization: Bearer`, and when it ends."""

    token: str
    expires_at: datetime
    user: UserOut


class GroupOut(Model):
    """A user group."""

    hid: str
    name: str
    description: str
    member_count: int
    roles: list[str]
    row_version: int
    created_at: datetime
    updated_at: datetime


class GroupDetail(GroupOut):
    """A user group with its members."""

    members: list[UserOut]


class GroupCreate(Model):
    """A new user group."""

    name: str = Field(min_length=1, max_length=100)
    description: str = ""


class GroupPatch(Model):
    """Fields of a user group to change, and the version they were read at."""

    row_version: int
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None


class GrantOut(Model):
    """A role granted to a user or to a group."""

    hid: str
    role: str
    user_hid: str | None
    group_hid: str | None
    target_name: str
    created_at: datetime


class GrantCreate(Model):
    """A role to grant to exactly one user or one group."""

    role: str
    user_hid: str | None = None
    group_hid: str | None = None


class ServiceTokenOut(Model):
    """A service token. The secret is not kept and cannot be shown again."""

    hid: str
    user_hid: str
    name: str
    created_at: datetime
    expires_at: datetime | None
    last_used_at: datetime | None
    revoked_at: datetime | None


class ServiceTokenCreate(Model):
    """A new service token."""

    name: str = Field(min_length=1, max_length=100)
    expires_at: datetime | None = None


class ServiceTokenCreated(Model):
    """A service token just created, with the secret that is shown this once."""

    token: ServiceTokenOut
    secret: str


class AuditEventOut(Model):
    """One event of the audit trail."""

    hid: str
    at: datetime
    actor_hid: str | None
    actor_name: str | None
    via: str
    request_id: str
    action: str
    record_type: str
    record_hid: str | None
    changes: list[dict[str, Any]]


class AboutHelp(Model):
    """Whom to ask: the team that runs this installation, each blank one null (P-169)."""

    organization: str | None
    email: str | None
    phone: str | None
    url: str | None


class About(Model):
    """What is running, by the name the site gives it, and whom to ask."""

    name: str = Field(description="the software, which is hirdir whatever the site calls it")
    version: str
    python: str
    sqlite: str
    schema_revision: str | None
    product_name: str = Field(description="the name the site gives the product (P-168)")
    help: AboutHelp


class LoadCeiling(Model):
    """The ceiling in force: the three settings of it (P-265)."""

    response_ms: int = Field(
        description="`busy_response_ms`: what `measures.response_ms` may reach. 0: not looked at."
    )
    cpu_percent: int = Field(
        description="`busy_cpu_percent`: what `measures.cpu_percent` may reach, which is "
        "up to 100 for each processor of the host. 0: not looked at."
    )
    over_seconds: int = Field(
        description="`busy_over_seconds`: over how long the measures are read, and how "
        "much longer a busy server is busy, by what came since, before it is very busy."
    )


class LoadMeasures(Model):
    """The two measures as the ceiling reads them now, over the last `over_seconds`."""

    response_ms: float | None = Field(
        description="How long requests take: the 95th percentile, in milliseconds, of "
        "the time taken by the reads and the changes of the API that came in that time, "
        "whatever each took, and of the time waited so far by those in flight, however "
        "long ago they came. Reports, exports and previews are not in it. A request's "
        "time begins when the server has the whole of it, its body with it. Null with "
        "fewer than twenty."
    )
    cpu_percent: float = Field(
        description="The processor time the process used, every thread of it, as a "
        "percentage of one processor. It passes 100 where several requests are in the "
        "database at once."
    )


class LoadSpread(Model):
    """The lowest, the average and the highest of a value. Null where there was none."""

    low: float | None
    average: float | None
    high: float | None


class LoadTimes(LoadSpread):
    """The times of the answers of the window, in milliseconds. `low`, `average` and
    `high` are of every answer but an answer of busy. The percentiles are of the
    requests of the measure, the reads and the changes of the API: each is one of their
    times, the shortest that so many in a hundred of them are no longer than."""

    p50: float | None = Field(description="Half of them took no longer. Null with none.")
    p95: float | None = Field(description="95 in a hundred took no longer. Null with none.")
    p99: float | None = Field(description="99 in a hundred took no longer. Null with none.")


class LoadBands(Model):
    """The requests of the measure answered in the window, by how long each took."""

    bounds_ms: list[float] = Field(
        description="The three bounds of the four bands, in milliseconds: a third of "
        "`busy_response_ms`, two thirds of it, and the ceiling. `[1000, 2000, 3000]` "
        "unless set, and those of 3000 where the setting is 0."
    )
    counts: list[int] = Field(
        description="Four counts: under the first bound, from it to under the second, "
        "from the second to the third, and past the third."
    )


class LoadTotals(Model):
    """What was answered in the window, and how."""

    requests: int = Field(description="Every request answered: the four below together.")
    ok: int = Field(description="Answered well: a status below 400.")
    not_accepted: int = Field(description="Not taken as asked: `4xx`.")
    failed: int = Field(
        description="Failed: `5xx`, the 503 of a change that waited for another among "
        "them, and an answer that was not sent to its last byte."
    )
    busy: int = Field(description="Answered 503 as busy, by a server past its ceiling.")
    response_ms: LoadTimes = Field(
        description="The time of an answer, in milliseconds, from when the server had "
        "the whole request, its body with it, to the last byte of its answer. An answer "
        "of busy is not in it."
    )
    bands: LoadBands
    cpu_percent: LoadSpread = Field(
        description="The processor time the process used, as a percentage of one "
        "processor: the lowest, the average and the highest of the steps that are whole. "
        "Each may pass 100."
    )


class LoadInFlight(Model):
    """The requests being answered now. The request that asks is not counted."""

    count: int = Field(
        description="Those whose body has not all come are counted: they wait for their "
        "sender, are in neither measure, and have no age."
    )
    oldest_ms: float | None = Field(
        description="How long the oldest has waited since the server had the whole of "
        "it, in milliseconds. Null with none."
    )


class LoadProcess(Model):
    """The server's process."""

    memory_bytes: int | None = Field(description="The memory it holds. Null where unknown.")


class LoadHost(Model):
    """What the host says of itself. Each is null where the host does not say."""

    memory_total_bytes: int | None
    memory_used_bytes: int | None = Field(description="The total less what is free.")
    memory_free_bytes: int | None = Field(description="What a new process could have.")
    disk_total_bytes: int | None = Field(description="Of the disk the inventory is kept on.")
    disk_free_bytes: int | None = Field(description="Of the disk the inventory is kept on.")
    processors: int | None
    load_1m: float | None = Field(description="The load average of the last minute.")


class LoadPoints(Model):
    """The steps of the window as lists side by side, the oldest first: entry `i` of each
    is the step that began `i` times `step_seconds` after `at`. The last is under way."""

    at: datetime = Field(description="When the first step began.")
    requests: list[int] = Field(description="The requests answered in the step.")
    average_ms: list[float | None] = Field(
        description="The average time of an answer. Null where nothing was answered."
    )
    high_ms: list[float | None] = Field(
        description="The longest time of an answer. Null where nothing was answered."
    )
    p50_ms: list[float | None] = Field(
        description="The time that half of the requests of the measure answered in the "
        "step took no longer than. Null where none was."
    )
    p95_ms: list[float | None] = Field(
        description="The time that 95 in a hundred of the requests of the measure "
        "answered in the step took no longer than. Null where none was."
    )
    cpu_percent: list[float | None] = Field(
        description="The processor time used, as a percentage of one processor, which "
        "may pass 100. Null in the step under way until a second of it has passed."
    )
    busy: list[int] = Field(description="The answers of busy given in the step.")


class Load(Model):
    """The server's own measures of its last ten minutes, kept in memory (P-265, P-266)."""

    state: Literal["ok", "busy", "very_busy"] = Field(
        description="`busy`: past the ceiling, and what is long by nature, a report, "
        "an export or a preview, is answered 503. `very_busy`: still so `over_seconds` "
        "later, by what came since, and every read is."
    )
    because: list[Literal["response_ms", "cpu_percent"]] = Field(
        description="The measures that are past the ceiling. Empty while `state` is `ok`."
    )
    health: Literal["good", "slow", "very_slow", "busy"] = Field(
        description="The health of the server in a word, which every answer of the API "
        "carries in `X-Hirdir-Health`. It stands on `measures.response_ms` against the "
        "thirds of its ceiling, `totals.bands.bounds_ms`: `good` under the first or "
        "with no measure, `slow` under the second, `very_slow` up to the third, `busy` "
        "past it. And `busy` whenever `state` is not `ok`, by either measure."
    )
    ceiling: LoadCeiling
    measures: LoadMeasures
    window_seconds: int = Field(description="How long the measures are kept: 600.")
    step_seconds: int = Field(description="The length of a step: 5.")
    started_at: datetime = Field(description="When the server started, and its measures.")
    at: datetime = Field(description="When this was read.")
    totals: LoadTotals
    in_flight: LoadInFlight
    process: LoadProcess
    host: LoadHost
    worker: Literal["running", "not_running", "in_process"] = Field(
        description="Whether the background work is being done: by the process of its "
        "own, by nothing, or by this process (P-267)."
    )
    points: LoadPoints


class Health(Model):
    """The answer of a health probe."""

    status: str
    detail: str = ""
