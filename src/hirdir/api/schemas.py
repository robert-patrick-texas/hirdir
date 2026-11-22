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
    """Why a server did not take a request: its health, and what it refuses (P-265)."""

    health: Literal["very_slow", "busy"] = Field(
        description="The health of the server, as `X-Hirdir-Health` says it: `very_slow` or `busy`."
    )
    because: list[Literal["response_ms", "cpu_percent"]] = Field(
        description="The measures the health stands on: how long requests take, the "
        "processor time the process uses as a percentage of one processor."
    )
    refusing: Literal["long", "reads"] = Field(
        description="What the server refuses: `long`, the reports, the exports and the "
        "previews; or `reads`, those and every other read of the API."
    )
    retry_after: int = Field(description="The seconds to wait, as `Retry-After` says.")


class AboutHelp(Model):
    """Whom to ask: the team that runs this installation, each blank one null (P-169)."""

    organization: str | None
    email: str | None
    phone: str | None
    url: str | None


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
        description="On the 503 of a server whose health had it take nothing of the "
        "request (P-265). Left out of every other problem, the 503 of a change that "
        "waited for another to be stored among them.",
    )
    help: AboutHelp | None = Field(
        default=None,
        description="On the 403 of `POST /auth/sign-in` of an account that gave the right "
        "access code and holds no role (P-299): whom to ask, as `help` of `GET /about` "
        "gives it, each blank one null, whatever `help_on_sign_in` says. Left out of "
        "every other problem.",
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


class OperatorBrief(Model):
    """An operator a person stands behind, as a user and a contact name it (P-280)."""

    hid: str
    label: str
    colour: str | None
    record_status: Literal["draft", "active", "retired"]


# A user's notes are as long as a contact's may be (P-281).
NOTES_LENGTH = 10_000
# What kind of account a user is (P-316): a person's, a service's, which does a fixed
# job, or an agent's, which decides what to change as a person does and is answerable
# to one.
UserKind = Literal["person", "service", "agent"]
# Why the role in force of an agent is lower than the role it holds (P-316).
CappedBy = Literal[
    "person_role", "person_no_role", "person_disabled", "person_retired", "never_admin"
]


class AccountRef(Model):
    """An account as another names it: the person an agent is answerable to, or an agent
    of a person (P-316)."""

    hid: str
    username: str
    name: str = Field(description="The name of its contact, or its username where it has none.")
    record_status: Literal["active", "retired"]


class UserGrant(Model):
    """One role an account holds, and where it comes from (P-307)."""

    hid: str = Field(description="The grant, as `/role-grants` names it.")
    role: Literal["viewer", "inventory", "admin"]
    group: GroupRef | None = Field(
        description="The group the role is granted to, which the account is in; null for a "
        "grant of the account's own."
    )


class UserOut(Model):
    """A user: the part of a person who signs in, a service account or an agent (P-172,
    P-316)."""

    hid: str
    username: str
    contact_hid: str | None
    contact: PersonRef | None = Field(
        description="The contact the user is. None for a service account and an agent, or a "
        "user not given one."
    )
    display_name: str = Field(description="The name of its contact; blank where it has none.")
    email: str = Field(description="The email of its contact; blank where it has none.")
    operators: list[OperatorBrief] = Field(
        description="The operators whose contact is the user's, retired ones among them, in "
        "the order of their labels; none for a user with no contact (P-280)."
    )
    notes: str | None = Field(
        description="What the account is for, who asked for it, when it is to end (P-281). "
        "For an Admin: answered by `GET /users` and `GET /users/{hid}` and the routes that "
        "change a user, and null from `GET /auth/me` and signing in, for anybody."
    )
    kind: UserKind = Field(
        description="`person`, `service` or `agent`, set when the account is made and not "
        "changed after (P-316)."
    )
    answerable_hid: str | None = Field(
        description="Of an agent alone: the person answerable for it (P-316). Null for the others."
    )
    answerable: AccountRef | None = Field(
        description="Of an agent alone: the person answerable for it, read now."
    )
    agents: list[AccountRef] = Field(
        description="Of a person: the agents answerable to them, the retired among them, by "
        "username. None for a service account or an agent."
    )
    disabled: bool
    record_status: Literal["active", "retired"] = Field(
        description="`retired`, the account of somebody who has left: it signs in with "
        "nothing and holds no role, group, code or token until an Admin brings it back. "
        "`disabled`, beside it, is an account that may not sign in for now (P-296)."
    )
    role: str | None = Field(description="The highest role held directly or through a group.")
    grants: list[UserGrant] = Field(
        description="Every grant that gives the account a role, of its own or of a group it "
        "is in: the highest role first, a grant of its own before those of groups, and the "
        "groups by name (P-307). `role` is the highest of them."
    )
    role_in_force: str | None = Field(
        description="The role the account's requests are held to now. For a person and a "
        "service account, `role`. For an agent, the lower of `role` and the role of the "
        "person answerable for it, and null where the person holds no role, is disabled or "
        "is retired, its tokens being refused then (P-316)."
    )
    role_capped_by: CappedBy | None = Field(
        description="Of an agent alone, where `role_in_force` is lower than `role`, why: "
        "the person's role is lower, `person_role`, or the person holds none, is disabled or "
        "is retired; or `never_admin`, an agent that holds Admin all the same, which no route "
        "gives it, held at Inventory. Null where nothing holds it lower."
    )
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


class NewOperator(Model):
    """A new operator, made with the user whose contact stands behind it (P-283)."""

    label: str | None = Field(
        default=None,
        max_length=40,
        description="Left out or blank, the username of the new user, which must then be "
        "an acceptable label: it is never shortened.",
    )
    colour: str | None = Field(
        default=None,
        max_length=20,
        description="In the form #1f6feb. Left out, the next that no operator has, as "
        "`next_for_operators` of `GET /colours` gives it; blank or null, none.",
    )
    description: str | None = Field(default=None, max_length=NOTES_LENGTH)


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
    kind: UserKind = Field(
        default="person",
        description="`person`, `service` or `agent`; not changed after (P-316). A service "
        "account and an agent take no contact, no access code and no operator: they hold "
        "tokens.",
    )
    answerable_hid: str | None = Field(
        default=None,
        max_length=36,
        description="Of an agent, and required of it: the person answerable for it, a user "
        "of the kind `person` who is not retired. Refused to the other kinds (P-316).",
    )
    access_code: str | None = Field(
        default=None, max_length=200, description="Left out, a code is generated."
    )
    role: str | None = Field(
        default=None,
        description="A role to grant at once. A person is given one, or a group in "
        "`group_hids` that grants one, or it is a `422` on `role` (P-299); a service account "
        "and an agent may have none. An agent is never Admin (P-316).",
    )
    group_hids: list[str] = Field(
        default=[],
        max_length=1000,
        description="The user groups to put the new user in, in the same change (P-282).",
    )
    operator: NewOperator | None = Field(
        default=None,
        description="An operator to make in the same change, whose contact is the user's: "
        "it needs `contact` or `contact_hid` (P-283).",
    )
    notes: str | None = Field(default=None, max_length=NOTES_LENGTH, description="Blank is none.")


class UserPatch(Model):
    """Fields of a user to change, and the version they were read at."""

    row_version: int
    username: str | None = Field(
        default=None, min_length=1, max_length=64, description="Another username (P-173)."
    )
    contact_hid: str | None = Field(
        default=None,
        max_length=36,
        description="Another contact; null for none. A service account and an agent have none.",
    )
    disabled: bool | None = None
    notes: str | None = Field(
        default=None, max_length=NOTES_LENGTH, description="Null or blank clears them (P-281)."
    )
    kind: UserKind | None = Field(
        default=None,
        description="The kind is not changed after the account is made: the kind it has is "
        "no change, and any other is a `422` on `kind` (P-316).",
    )
    answerable_hid: str | None = Field(
        default=None,
        max_length=36,
        description="Of an agent: another person answerable for it, a user of the kind "
        "`person` who is not retired, which hands the agent over. Null, or given for another "
        "kind, is a `422` on `answerable_hid` (P-316).",
    )


# --- retired accounts, and a person retired together (P-291, P-296 to P-298) ---------

# Which accounts a list of users holds: `no`, those that are not retired; `yes`, the
# retired with the rest; `only`, the retired alone (P-296).
Retired = Literal["no", "yes", "only"]


class LinkedUser(Model):
    """The user of a person, as the chain of the person shows it (P-297), or an agent
    answerable to that user (P-316)."""

    hid: str
    username: str
    record_status: Literal["active", "retired"]
    disabled: bool
    role: str | None = Field(description="The highest role held directly or through a group.")


class LinkedContact(Model):
    """The contact of a person, as the chain of the person shows it (P-297)."""

    hid: str
    name: str
    email: str | None
    record_status: Literal["draft", "active", "retired"]
    uses: int = Field(
        description="How many records name it, as `uses` of `GET /contacts/{hid}` counts them."
    )


class LinkedOperator(Model):
    """An operator of a person, as the chain of the person shows it (P-297)."""

    hid: str
    label: str
    colour: str | None
    record_status: Literal["draft", "active", "retired"]
    uses: int = Field(description="How many items, groups and places are given it as their own.")


class Person(Model):
    """The person a user, a contact or an operator belongs to: the user, the contact
    that joins them and every operator of that contact, the retired among them, marked
    so. The record asked for is among them (P-291, P-297)."""

    user: LinkedUser | None = Field(
        description="The user whose contact this is, a retired one too; null where there is none."
    )
    contact: LinkedContact | None = Field(
        description="The contact; null for a user and for an operator that has none."
    )
    operators: list[LinkedOperator] = Field(
        description="Every operator of the contact, in the order of their labels."
    )
    agents: list[LinkedUser] = Field(
        description="Every agent answerable to the user, the retired among them, by username "
        "(P-316); none where there is no user, or it is no person."
    )


class OperatorPlan(Model):
    """What becomes of one operator of a person who is retired (P-297)."""

    hid: str = Field(max_length=36)
    action: Literal["retire", "keep", "open", "hand_over"] = Field(
        description="`retire` releases what the label is on; `keep` leaves it as it is; "
        "`open` leaves the label with no contact; `hand_over` gives it to `contact_hid`."
    )
    contact_hid: str | None = Field(
        default=None,
        max_length=36,
        description="With `hand_over`, and with no other action: the contact, not retired "
        "and not this person's, who is behind the label from then on.",
    )


class AgentPlan(Model):
    """What becomes of one agent of a person who is retired (P-316)."""

    hid: str = Field(max_length=36)
    action: Literal["retire", "hand_over"] = Field(
        description="`retire` retires the agent with the person, its tokens revoked; "
        "`hand_over` makes `user_hid` answerable for it."
    )
    user_hid: str | None = Field(
        default=None,
        max_length=36,
        description="With `hand_over`, and with no other action: the person answerable for "
        "the agent from then on, a user of the kind `person`, not retired and not the one "
        "retired.",
    )


class Linked(Model):
    """What becomes of each record linked to the one a retirement is of (P-297). Every
    linked record that is not retired is said, and the record the route is on is not."""

    user: Literal["retire", "keep"] | None = None
    contact: Literal["retire", "keep"] | None = None
    operators: list[OperatorPlan] = Field(default=[], max_length=1000)
    agents: list[AgentPlan] = Field(
        default=[],
        max_length=1000,
        description="Where the request retires a user that is a person: what becomes of each "
        "agent answerable to it that is not retired, each to be said (P-316). Said where "
        "no user is retired, it is a `422`.",
    )


class Retirement(Model):
    """A retirement of a user, a contact or an operator: the version the record was read
    at and, where anything is linked to it that is not retired, what becomes of each."""

    row_version: int
    linked: Linked | None = Field(
        default=None, description="Left out for a record with nothing linked, as before."
    )


class OperatorBack(Model):
    """A retired operator of the contact, brought back with the user (P-298)."""

    hid: str = Field(max_length=36)
    action: Literal["bring_back"]


class LinkedBack(Model):
    """What is brought back with a user (P-298)."""

    contact: Literal["bring_back"] | None = Field(
        default=None,
        description="To be said where the contact of the user is retired: an account does "
        "not stand on a retired contact.",
    )
    operators: list[OperatorBack] = Field(
        default=[],
        max_length=1000,
        description="Those of the contact that are retired and are to be brought back; "
        "none need be said.",
    )


class BringBack(Model):
    """A retired user brought back, the role it is given and what is brought back with
    it (P-298, P-299)."""

    row_version: int
    linked: LinkedBack | None = None
    role: str | None = Field(
        default=None,
        description="`viewer`, `inventory` or `admin`, granted in the same change. A person "
        "is given one, since an account with no role does not sign in: left out, it is a "
        "`422` on `role`. A service account and an agent may be brought back with none "
        "(P-299), and an agent is never Admin (P-316).",
    )
    answerable_hid: str | None = Field(
        default=None,
        max_length=36,
        description="Of an agent: the person answerable for it from then on, a user of the "
        "kind `person` who is not retired. Left out, it stays its person's; where that "
        "person is retired, it is a `409` on `answerable_hid` that names them. Given for "
        "another kind, a `422` (P-316).",
    )


class UserBroughtBack(Model):
    """A user brought back, with its new access code, shown this once; a service account
    and an agent have none (P-296)."""

    user: UserOut
    access_code: str | None


class AccessCodeSet(Model):
    """A new access code for a user. Left out, a code is generated."""

    access_code: str | None = Field(default=None, max_length=200)


class AccessCodeOut(Model):
    """The access code just set, shown this once."""

    access_code: str


class NewAccessCode(Model):
    """An access code made by the server for a form to send, stored nowhere (P-300)."""

    access_code: str = Field(
        description="Groups of four, three or as many more as make it at least as long as "
        "the setting `access_code_min_length` asks."
    )


class SignIn(Model):
    """A username and access code."""

    username: str = Field(min_length=1, max_length=64)
    access_code: str = Field(min_length=1, max_length=200)


# --- a person's own profile (P-289, P-294, P-295) -------------------------------------


class OwnContact(Model):
    """The contact the signed-in person is, as their profile reads and changes it."""

    hid: str
    name: str
    email: str | None
    phone: str | None
    phone2: str | None
    organization: str | None
    record_status: Literal["draft", "active", "retired"]
    row_version: int


class OwnOperator(Model):
    """An operator the signed-in person is behind, as their profile reads and changes it."""

    hid: str
    label: str
    colour: str | None
    record_status: Literal["draft", "active"]
    row_version: int


class MeOut(Model):
    """The signed-in user, with what is their own: the answer of `GET /auth/me` and of
    the routes under it, and `user` in the answer of signing in. It is a user as the
    routes of users answer one, but for four things: `contact` and `operators` carry
    what the profile changes, and the version of each; `notes` is null; and there is no
    `record_status`, which would say `active` always, since whoever reads this is
    signed in and a retired account signs in nowhere (P-296)."""

    hid: str
    username: str
    contact_hid: str | None
    contact: OwnContact | None = Field(
        description="The contact the person is, with the version to change it at. None for "
        "a service account and an agent, or a user not given one."
    )
    display_name: str = Field(description="The name of its contact; blank where it has none.")
    email: str = Field(description="The email of its contact; blank where it has none.")
    operators: list[OwnOperator] = Field(
        description="The operators that are not retired whose contact is the person's, in "
        "the order of their labels, each with the version to change it at. None for a "
        "user with no contact, or with one that is retired: nobody is behind the labels "
        "of a retired contact (P-280)."
    )
    notes: str | None = Field(
        description="Always null: the notes on an account are an Admin's, answered by the "
        "routes of users alone (P-281)."
    )
    kind: UserKind = Field(description="`person`, `service` or `agent` (P-316).")
    answerable_hid: str | None = Field(
        description="Of an agent alone: the person answerable for it (P-316)."
    )
    answerable: AccountRef | None = Field(
        description="Of an agent alone: the person answerable for it, read now (P-316)."
    )
    agents: list[AccountRef] = Field(
        description="Of a person: the agents answerable to them, as on a user (P-316)."
    )
    disabled: bool
    role: str | None = Field(description="The highest role held directly or through a group.")
    grants: list[UserGrant] = Field(
        description="Each role held and where it comes from, as on a user (P-307)."
    )
    role_in_force: str | None = Field(
        description="The role the requests of this session or token are held to: `role`, "
        "or for an agent the lower of `role` and its person's (P-316)."
    )
    role_capped_by: CappedBy | None = Field(
        description="Of an agent alone, where its person holds it lower than `role`, why, as "
        "on a user (P-316)."
    )
    groups: list[GroupRef]
    last_sign_in_at: datetime | None
    row_version: int
    created_at: datetime
    updated_at: datetime


class OwnContactPatch(Model):
    """What a person changes of the contact they are, and the version it was read at.
    Nothing else of a contact is taken: not its notes, its tags or its state."""

    row_version: int
    name: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=254, description="Null or blank is none.")
    phone: str | None = Field(default=None, max_length=50, description="Null or blank is none.")
    phone2: str | None = Field(default=None, max_length=50, description="Null or blank is none.")
    organization: str | None = Field(
        default=None, max_length=200, description="Null or blank is none."
    )


class OwnOperatorPatch(Model):
    """What a person changes of an operator they are behind, and the version it was read
    at. Nothing else of an operator is taken: not who is behind it, nor its state."""

    row_version: int
    label: str | None = Field(default=None, max_length=40)
    colour: str | None = Field(
        default=None, max_length=20, description="In the form #1f6feb. Null or blank is none."
    )


class OwnAccessCode(Model):
    """The access code a person has, and the one they take in its place."""

    current_access_code: str = Field(min_length=1, max_length=200)
    access_code: str = Field(
        max_length=200,
        description="At least as long as the setting `access_code_min_length` says, not "
        "blank, with no space at its beginning or end, and not the current one (P-300).",
    )


class SessionOut(Model):
    """A session: the token to send as `Authorization: Bearer`, and when it ends."""

    token: str
    expires_at: datetime
    user: MeOut


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
    """A token of a service account or an agent (P-316). The secret is not kept and
    cannot be shown again."""

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
    actor_kind: UserKind | None = Field(
        description="The kind of the account that acted, `person`, `service` or `agent`; "
        "null for the system (P-316)."
    )
    for_hid: str | None = Field(
        description="Of an event made by an agent: the person it was answerable to when the "
        "event was made. Null for every other (P-316)."
    )
    for_name: str | None = Field(
        description="The username of that person, read now: a history writes "
        "`agent-reconcile for sam`."
    )
    via: str
    request_id: str
    action: str
    record_type: str
    record_hid: str | None
    changes: list[dict[str, Any]]


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
        description="`busy_response_ms`: what `measures.response_ms` may reach before "
        "the health is `busy`; its thirds are the bounds of the other words. 0: nothing "
        "is refused for it."
    )
    cpu_percent: int = Field(
        description="`busy_cpu_percent`: what `measures.cpu_percent` may reach before "
        "the health is `very_slow` at the least; up to 100 for each processor of the "
        "host. 0: not looked at."
    )
    over_seconds: int = Field(
        description="`busy_over_seconds`: over how long the measures are read, and for "
        "how long after it last refused its reads the server refuses what is long."
    )
    fewest_requests: int = Field(
        description="`busy_fewest_requests`, 21: with fewer reads than this in "
        "`measures.reads`, nothing is refused for time whatever the health says. They "
        "are too few to be load, and of twenty the percentile is one request alone."
    )


class LoadMeasures(Model):
    """The two measures as the ceiling reads them now, over the last `over_seconds`."""

    response_ms: float | None = Field(
        description="How long requests take: the 95th percentile, in milliseconds, of "
        "the time taken by the reads and the changes of the API that came in that time, "
        "whatever each took, and of the time waited so far by those in flight, however "
        "long ago they came. It is the longest of twenty or fewer, the second longest "
        "of twenty-one to forty, and so on. Reports, exports and previews are not in "
        "it. A request's time begins when the server has the whole of it, its body "
        "with it. Null with no request."
    )
    requests: int = Field(description="How many requests `response_ms` is of.")
    reads_ms: float | None = Field(
        description="The same percentile of the reads alone, a sign-in and a change "
        "that is stored left out: by it, and not by `response_ms`, what is refused is "
        "decided, since a read is never refused for a change that was slow. Null with "
        "no read."
    )
    reads: int = Field(
        description="How many reads `reads_ms` is of. With fewer than "
        "`ceiling.fewest_requests`, nothing is refused for time."
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
    `high` are of every answer but one that was refused. The percentiles are of the
    requests of the measure, the reads and the changes of the API: each is one of their
    times, the k-th longest, k being what the percentile leaves above it in a hundred
    of them, rounded up."""

    p50: float | None = Field(description="Half of them took longer. Null with none.")
    p95: float | None = Field(description="5 in a hundred took as long. Null with none.")
    p99: float | None = Field(description="1 in a hundred took as long. Null with none.")


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


class LoadWho(Model):
    """Who asked a request: the account, a person's, a service's or an agent's (P-316).
    `unnamed` where nothing verifiable said who: a sign-in, a token that did not hold, a
    request with none; its `hid` and `username` are null."""

    kind: Literal["person", "service", "agent", "unnamed"]
    hid: str | None
    username: str | None


class LoadSlow(Model):
    """One of the slowest requests of the last ten minutes. Its path as it was asked
    and its query are not kept: no identifier and no word of a search."""

    at: datetime = Field(description="When the server had the whole of it.")
    method: str
    route: str | None = Field(
        description="The route as its pattern, `/api/v1/items/{hid}`. Null for a "
        "request that no route answers."
    )
    ms: float = Field(description="How long its answer took, in milliseconds.")
    status: int
    request_id: str = Field(description="`X-Request-Id` of its answer, as the log has it.")
    who: LoadWho


class LoadPerson(Model):
    """What one account met in the last ten minutes."""

    kind: Literal["person", "service", "agent", "unnamed", "others"] = Field(
        description="`person`, `service` or `agent`: an account, by its kind (P-316). "
        "`unnamed`: the requests that "
        "nothing verifiable named an account for, together. `others`: the accounts "
        "past the fifty that are counted each by itself, together."
    )
    hid: str | None = Field(description="Of the account. Null for `unnamed` and `others`.")
    username: str | None = Field(description="Null for `unnamed` and `others`.")
    requests: int = Field(description="Every request of the API, those refused among them.")
    bands: list[int] = Field(
        description="Its requests of the measure by how long each took: four counts, by "
        "the bounds of `totals.bands` as they were when each was answered."
    )
    slowest_ms: float | None = Field(
        description="The longest of its requests of the measure. Null with none."
    )
    busy: int = Field(description="How many of its requests were answered 503 as busy.")
    failed: int = Field(description="How many failed: `5xx`.")
    last_at: datetime = Field(description="When the last of its requests came.")


class Load(Model):
    """The server's own measures of its last ten minutes, kept in memory (P-265, P-266)."""

    health: Literal["good", "slow", "very_slow", "busy"] = Field(
        description="The health of the server in a word, the colour of the mark: "
        "`measures.response_ms` against the thirds of its ceiling, "
        "`totals.bands.bounds_ms`. `good` under the first or with no request, `slow` "
        "under the second, `very_slow` up to the third, `busy` past it. The processor "
        "past its ceiling makes it `very_slow` at the least, and it is never better "
        "than what is refused says. Every answer of the API carries it in "
        "`X-Hirdir-Health`, with `refusing`, as they are when the answer begins."
    )
    because: list[Literal["response_ms", "cpu_percent"]] = Field(
        description="The measures the health stands on. Empty while it is `good`."
    )
    refusing: Literal["nothing", "long", "reads"] = Field(
        description="What the server answers 503 Busy: `long`, the reports, the exports "
        "and the previews, or `reads`, those and every other read of the API. It is "
        "decided by the reads alone, `measures.reads_ms`, where there is load to shed: "
        "`long` where they are at two thirds of the ceiling or past it, and `reads` "
        "where they are past the ceiling, with `ceiling.fewest_requests` or more in "
        "`measures.reads`. With fewer it is `nothing` for time whatever the health, "
        "and so it is where only the changes are slow. The processor past its ceiling "
        "refuses `long` whatever the count, and so does a server for `over_seconds` "
        "after it last refused `reads`. A measure whose ceiling is 0 refuses nothing."
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
    slowest: list[LoadSlow] = Field(
        description="The ten slowest requests of the measure answered in the window, "
        "the slowest first. Those in flight are not in it."
    )
    slowest_long: list[LoadSlow] = Field(
        description="The five slowest of what is long by nature, the reports, the "
        "exports and the previews, which are in no measure."
    )
    people: list[LoadPerson] = Field(
        description="Who asked anything of the API in the window, and what each met: "
        "whoever had it worst first, by the requests past the ceiling and those "
        "refused, then by the slowest time. After the accounts, `unnamed` and `others`."
    )


class Health(Model):
    """The answer of a health probe."""

    status: str
    detail: str = ""
