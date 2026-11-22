"""The input formats: a telephone number written in a pattern an Admin chooses, and an
email address kept in lower case (P-293, P-322).

What is here works on text alone. The settings that say which formats are on,
`phone_formats` and `email_lower_case`, are read by `hirdir.domain.settings`, which
gives them as `Formats`; a contact and whom to ask apply them to what comes in, by
every way in. The third format, Title Case of a person's name (`title_case_names`), is
the web page's alone, and never applied here. The server and the page are held to one
list of cases, `contract/formats.json`.

A format never refuses a value: a number that no pattern fits, or that holds what is
not part of a number's form, such as the letters of an extension, is kept as typed. And
a number written in the form of one of the patterns already is kept as it is, so that a
number formatted once is formatted the same again: what the page writes as a person
leaves the box is what the server saves, and an export loads back as no change.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

# The two patterns that P-293 names, offered beside one of an Admin's own.
OFFERED = ("###-###-####", "+1 (###) ###-####")
# A pattern is 4 to 40 characters, with four places for a digit at least. A number is
# written as long as its pattern, so that it fits wherever a number is kept: `help_phone`
# holds 40 characters, and a contact's numbers 50.
FEWEST_CHARACTERS = 4
MOST_CHARACTERS = 40
FEWEST_PLACES = 4
PLACE = "#"
PLUS = "+"
DIGITS = frozenset("0123456789")
# What a pattern holds between its digits and its places, and what a number may hold
# beside its digits and still be taken as its digits.
MARKS = frozenset(" +-()./")
# What a pattern is, in the words a refusal of one gives.
SAID = (
    f"a pattern of {FEWEST_CHARACTERS} to {MOST_CHARACTERS} characters: # for each digit, "
    f"{FEWEST_PLACES} at least; digits before the first # alone, the code of a country such "
    "as the 1 of +1 (###) ###-####; and spaces and + - ( ) . / between them"
)


@dataclass(frozen=True)
class Pattern:
    """A pattern of a telephone number."""

    text: str
    # The digits before its first place, written once: the code of a country.
    leading: str
    # How many digits it writes in its places.
    places: int
    # Whether it writes a + before its first digit or place.
    plus: bool

    def fits(self, digits: str, plus: bool) -> str | None:
        """Return the digits that go in the places of the pattern, or None where a
        number of these digits does not fit it.

        A number fits where its digits are the pattern's leading digits followed by as
        many as it has places, or, typed with no + before them, where they are as many
        as its places. A number typed with a + gives its country's code among its
        digits: a pattern of no leading digits fits it only where the pattern writes a
        + of its own, so that a format drops no code and puts none in place of another.
        """
        lead = self.leading
        if (
            digits.startswith(lead)
            and len(digits) == len(lead) + self.places
            and (lead or self.plus or not plus)
        ):
            return digits[len(lead) :]
        if not plus and len(digits) == self.places:
            return digits
        return None

    def writes(self, value: str) -> bool:
        """Say whether value is in the form of the pattern: its characters exactly as
        the pattern writes them, a digit 0 to 9 at each place."""
        return len(value) == len(self.text) and all(
            char in DIGITS if want == PLACE else char == want
            for char, want in zip(value, self.text, strict=True)
        )

    def write(self, digits: str) -> str:
        """Return the pattern with the digits in its places, in their order."""
        given = iter(digits)
        return "".join(next(given) if char == PLACE else char for char in self.text)


def fault(text: str) -> str | None:
    """Say what keeps text from being a pattern, or None where it is one."""
    if not FEWEST_CHARACTERS <= len(text) <= MOST_CHARACTERS:
        return f"is {len(text)} characters long"
    for char in text:
        if char != PLACE and char not in DIGITS and char not in MARKS:
            return f"holds {char}, which a pattern does not"
    if text.count(PLACE) < FEWEST_PLACES:
        return f"has fewer than {FEWEST_PLACES} #"
    if any(char in DIGITS for char in text[text.index(PLACE) :]):
        return "has a digit after its first #"
    return None


def pattern(text: str) -> Pattern | None:
    """Return text as a pattern, or None where it is none."""
    if fault(text) is not None:
        return None
    head = text[: text.index(PLACE)]
    before_digits = head[: _first_digit(head)]
    return Pattern(
        text=text,
        leading="".join(char for char in head if char in DIGITS),
        places=text.count(PLACE),
        plus=PLUS in before_digits,
    )


def _first_digit(text: str) -> int:
    return next((place for place, char in enumerate(text) if char in DIGITS), len(text))


def phone(value: str | None, patterns: Iterable[Pattern]) -> str | None:
    """Return a telephone number written in the first pattern that fits its digits, or
    as it is typed where it holds anything but digits and the marks of a pattern, or
    where no pattern fits.

    A number in the form of one of the patterns already is kept as it is, though an
    earlier pattern fits its digits: so what a pattern writes, which is in its form, is
    written the same again (the review of 0.9.18).
    """
    if not isinstance(value, str) or any(
        char not in DIGITS and char not in MARKS for char in value
    ):
        return value
    tried = tuple(patterns)
    if any(one.writes(value) for one in tried):
        return value
    digits = "".join(char for char in value if char in DIGITS)
    plus = PLUS in value[: _first_digit(value)]
    for one in tried:
        placed = one.fits(digits, plus)
        if placed is not None:
            return one.write(placed)
    return value


def email(value: str | None, lower_case: bool) -> str | None:
    """Return an email address in lower case where the format is on."""
    return value.lower() if lower_case and isinstance(value, str) else value


@dataclass(frozen=True)
class Formats:
    """The formats in force, as the settings say them."""

    patterns: tuple[Pattern, ...] = ()
    email_lower_case: bool = False

    def phone(self, value: str | None) -> str | None:
        """Return a telephone number as it is saved."""
        return phone(value, self.patterns)

    def email(self, value: str | None) -> str | None:
        """Return an email address as it is saved."""
        return email(value, self.email_lower_case)


def of(phone_formats: Any, email_lower_case: Any) -> Formats:
    """Return the formats the values of the two settings say. A pattern that is not one,
    as one stored before its rule was what it is, is passed over."""
    texts = phone_formats if isinstance(phone_formats, list) else []
    found = (pattern(text) for text in texts if isinstance(text, str))
    return Formats(
        patterns=tuple(one for one in found if one is not None),
        email_lower_case=email_lower_case is True,
    )
