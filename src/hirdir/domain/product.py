"""The name a site gives the product, and whom to ask: the team that runs it (P-168, P-169).

Both are settings of the inventory, which an Admin changes on the Settings page and which
are audited as every setting is. What they take is checked here; `settings.py` lists
them with the others. The page the server serves carries the name, and whom to ask only
where `help_on_sign_in` says so, since anyone who reaches the site may fetch that page.
"""

import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from html import escape
from typing import Any

from sqlalchemy.orm import Session

from hirdir.domain import records
from hirdir.domain.errors import Invalid

DEFAULT_NAME = "hirdir"
MOST_NAME = 40
MOST_ORGANIZATION = 200
MOST_EMAIL = 254
MOST_PHONE = 40
# What a phone number holds besides letters and digits: the `/` that a pattern of
# `phone_formats` may write among them (P-322).
PHONE_MARKS = frozenset(" +-().,#*/")
# What text shown in a page and written into one never holds (as a link's text, D-189).
MARKS = ("<", ">")
# What an email address to write to holds none of: what would add to the message a
# `mailto:` link opens, a copy to another, a subject or a body, or make it another link.
NOT_IN_AN_EMAIL = frozenset("?&=%/:;,\"'")
# The characters that change the direction of the text around them, which could make a
# name read as another. The joiners that some scripts and emoji need are taken.
DIRECTION = frozenset("\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")
HELP_KEYS = ("help_organization", "help_email", "help_phone", "help_url")
PAGE_KEYS = ("product_name", *HELP_KEYS, "help_on_sign_in")
# In the name of a file, each run of anything else is one hyphen.
_NOT_IN_A_FILE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def _refuse(key: str, expected: str) -> Invalid:
    return Invalid(f"the value of {key} is not acceptable", {"value": expected})


def _plain(value: Any) -> str | None:
    """Return text without the spaces at either end, or None for anything else or for
    text that holds a mark, a control character, one that changes the direction of the
    text, one that is not a character, or nothing."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or any(mark in text for mark in MARKS):
        return None
    for char in text:
        if char in DIRECTION or unicodedata.category(char) in ("Cc", "Cs", "Co", "Cn"):
            return None
    return text


def check_name(value: Any) -> str:
    """The product name: 1 to 40 characters, with neither `<`, `>` nor a control one."""
    expected = (
        f"a name of 1 to {MOST_NAME} characters, with neither < nor > nor a control character"
    )
    text = _plain(value)
    if text is None or len(text) > MOST_NAME:
        raise _refuse("product_name", expected)
    return text


def check_organization(value: Any) -> str:
    """The group that runs the installation: 1 to 200 characters, with neither mark."""
    expected = (
        f"a name of 1 to {MOST_ORGANIZATION} characters, with neither < nor > nor a "
        "control character"
    )
    text = _plain(value)
    if text is None or len(text) > MOST_ORGANIZATION:
        raise _refuse("help_organization", expected)
    return text


def check_email(value: Any) -> str:
    """A plain email address: one `@`, something before it, a domain with a dot after it,
    and nothing that would add to the message a link to it opens."""
    expected = (
        "a plain email address, such as tools@example.net, with no space and none of "
        "? & = % / : ; , \" '"
    )
    text = _plain(value)
    if text is None or len(text) > MOST_EMAIL:
        raise _refuse("help_email", expected)
    if any(char.isspace() or char in NOT_IN_AN_EMAIL for char in text):
        raise _refuse("help_email", expected)
    local, at, domain = text.partition("@")
    if not at or not local or "@" in domain or "." not in domain or ".." in text:
        raise _refuse("help_email", expected)
    if domain.startswith(".") or domain.endswith(".") or local.startswith("."):
        raise _refuse("help_email", expected)
    return text


def check_phone(value: Any) -> str:
    """A number to call, with a digit in it, shown as it is saved: an Admin's setting
    writes it in a pattern of `phone_formats` first (P-322)."""
    expected = (
        f"a number to call, at most {MOST_PHONE} characters of digits, spaces, letters "
        "and + - ( ) . , # * /"
    )
    text = _plain(value)
    if text is None or len(text) > MOST_PHONE:
        raise _refuse("help_phone", expected)
    if not all(_digit(char) or char.isalpha() or char in PHONE_MARKS for char in text):
        raise _refuse("help_phone", expected)
    if not any(_digit(char) for char in text):
        raise _refuse("help_phone", expected)
    return text


def _digit(char: str) -> bool:
    return char in "0123456789"


def check_url(value: Any) -> str:
    """An address on the web, as a link of D-189 is, and with neither mark."""
    expected = "an address that begins with https:// or http://, with no space"
    text = _plain(value)
    if text is None:
        raise _refuse("help_url", expected)
    try:
        url = records.checked_url("help_url", text)
    except Invalid:
        raise _refuse("help_url", expected) from None
    if url is None:
        raise _refuse("help_url", expected)
    return url


def check_flag(key: str) -> Any:
    """True or false, and nothing that only looks like one."""

    def check(value: Any) -> bool:
        if not isinstance(value, bool):
            raise _refuse(key, "true or false")
        return value

    return check


# --- what is read ------------------------------------------------------------------


@dataclass(frozen=True)
class Help:
    """Whom to ask: each blank one is None."""

    organization: str | None
    email: str | None
    phone: str | None
    url: str | None

    @property
    def named(self) -> bool:
        """Whether any of them is set."""
        return any(value is not None for value in asdict(self).values())


def _values(db: Session) -> dict[str, Any]:
    """Return the settings of the name and of whom to ask, read at once."""
    from hirdir.domain import settings

    return settings.values(db, PAGE_KEYS)


def name(db: Session) -> str:
    """Return the product name in force."""
    return str(_values(db)["product_name"])


def file_stem(product_name: str) -> str:
    """Return the product name as the first part of a file's name: letters lose their
    accents, each run of what a file name had better not hold is then one hyphen, a
    hyphen or a dot at either end is taken off, and hirdir stands where nothing is
    left."""
    plain = "".join(
        char
        for char in unicodedata.normalize("NFKD", product_name)
        if not unicodedata.category(char).startswith("M")
    )
    stem = _NOT_IN_A_FILE_NAME.sub("-", plain).strip("-.")
    return stem or DEFAULT_NAME


def _help(values: dict[str, Any]) -> Help:
    return Help(*(values[key] if isinstance(values[key], str) else None for key in HELP_KEYS))


def help_of(db: Session) -> Help:
    """Return whom to ask, as the settings say."""
    return _help(_values(db))


def page_facts(db: Session) -> dict[str, Any]:
    """Return what the page that is served before signing in carries: the product name,
    and whom to ask only where an Admin chose to show it there and one of them is set.
    It is one query, as the page is served to whoever asks."""
    values = _values(db)
    shown = _help(values)
    on_page = values["help_on_sign_in"] is True and shown.named
    return {
        "product_name": str(values["product_name"]),
        "help": asdict(shown) if on_page else None,
    }


# What the page carries when the database cannot be read: it is the sign-in page, and is
# served all the same, named as hirdir is, with nobody named.
UNREAD = {"product_name": DEFAULT_NAME, "help": None}


def page_attribute(facts: dict[str, Any]) -> str:
    """Return the facts as JSON for an attribute of the page, escaped as one is."""
    return escape(json.dumps(facts, ensure_ascii=True, separators=(",", ":")), quote=True)
