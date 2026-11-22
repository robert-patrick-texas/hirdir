"""The input formats, held to the cases that the web page is held to as well (P-322)."""

import json
import random
from pathlib import Path
from typing import Any

import pytest

from hirdir.db.models import Base
from hirdir.domain import formats, product, settings
from hirdir.domain.errors import Invalid
from hirdir.io.entities import entity

ROOT = Path(__file__).resolve().parents[2]
CASES = json.loads((ROOT / "contract" / "formats.json").read_text(encoding="utf-8"))
SETTINGS = ("phone_formats", "email_lower_case", "title_case_names")


def _of(format_: str) -> list[dict[str, Any]]:
    return [case for case in CASES["cases"] if case["format"] == format_]


def _patterns(texts: list[str]) -> tuple[formats.Pattern, ...]:
    found = tuple(formats.pattern(text) for text in texts)
    assert None not in found, texts
    return tuple(one for one in found if one is not None)


def _seen(case: dict[str, Any]) -> str:
    return f"{case['setting']} {case['typed']!r}"


@pytest.mark.parametrize("case", _of("phone_formats"), ids=_seen)
def test_a_number_is_written_in_the_first_pattern_that_fits_or_kept_as_typed(
    case: dict[str, Any],
) -> None:
    patterns = _patterns(case["setting"])
    assert formats.phone(case["typed"], patterns) == case["kept"]
    # What a format writes it writes the same again: a number tidied on the page is
    # saved as the page shows it.
    assert formats.phone(case["kept"], patterns) == case["kept"]
    assert formats.of(case["setting"], False).phone(case["typed"]) == case["kept"]


@pytest.mark.parametrize("case", _of("email_lower_case"), ids=_seen)
def test_an_email_address_is_kept_in_lower_case_where_the_format_is_on(
    case: dict[str, Any],
) -> None:
    assert formats.email(case["typed"], case["setting"]) == case["kept"]
    assert formats.of([], case["setting"]).email(case["typed"]) == case["kept"]


def test_every_case_is_of_a_setting_and_a_value_it_takes() -> None:
    assert {case["format"] for case in CASES["cases"]} == set(SETTINGS)
    for case in CASES["cases"]:
        spec = settings.SPECS[case["format"]]
        assert spec.check(case["setting"]) == case["setting"], case
        assert isinstance(case["typed"], str), case
        assert isinstance(case["kept"], str), case
    # The cases of Title Case are the page's: the server keeps the setting and applies it
    # nowhere, and they are here for it to read.
    assert len(_of("title_case_names")) >= 10


@pytest.mark.parametrize("case", CASES["patterns"], ids=lambda case: repr(case["pattern"]))
def test_a_pattern_is_taken_as_the_rule_says_or_refused_saying_why(case: dict[str, Any]) -> None:
    check = settings.SPECS["phone_formats"].check
    if case["kept"] is None:
        with pytest.raises(Invalid) as refused:
            check([case["pattern"]])
        said = refused.value.fields["value"]
        assert said.startswith(f"a list of patterns, each {formats.SAID}. "), said
        assert formats.fault(case["pattern"].strip()) is not None or not case["pattern"].strip()
    else:
        assert check([case["pattern"]]) == [case["kept"]]
        assert formats.pattern(case["kept"]) is not None


def test_the_setting_of_patterns_is_a_list_kept_in_its_order_and_each_once() -> None:
    check = settings.SPECS["phone_formats"].check
    assert check([]) == []
    assert check(["+1 (###) ###-####", " ###-###-#### ", "+1 (###) ###-####"]) == [
        "+1 (###) ###-####",
        "###-###-####",
    ]
    for wrong in ("###-###-####", None, 12, [12], [["###-####"]], {"a": "###-####"}):
        with pytest.raises(Invalid):
            check(wrong)
    # A refusal names the pattern and what is wrong with it.
    with pytest.raises(Invalid) as refused:
        check(["###-###-####", "### x ####"])
    assert refused.value.fields["value"].endswith(". ### x #### holds x, which a pattern does not")
    with pytest.raises(Invalid) as refused:
        check(["###-###-##00"])
    assert refused.value.fields["value"].endswith("has a digit after its first #")


def test_the_settings_start_as_the_owner_chose_and_offer_the_two_patterns() -> None:
    assert settings.SPECS["phone_formats"].default == []
    assert settings.SPECS["email_lower_case"].default is True
    assert settings.SPECS["title_case_names"].default is True
    options = settings.SPECS["phone_formats"].takes.options
    assert options is not None
    assert options() == ("###-###-####", "+1 (###) ###-####")
    for key in ("email_lower_case", "title_case_names"):
        check = settings.SPECS[key].check
        assert (check(True), check(False)) == (True, False)
        for wrong in ("true", 1, None, "yes"):
            with pytest.raises(Invalid):
                check(wrong)


def test_a_number_a_pattern_writes_fits_wherever_a_number_is_kept() -> None:
    # A number is as long as the pattern that writes it, and the longest pattern fits
    # help_phone, a contact's two numbers and their columns in a file.
    table = Base.metadata.tables["contacts"]
    columns = [entity("contacts").column(name) for name in ("phone", "phone2")]
    limits = [
        product.MOST_PHONE,
        *(getattr(table.c[name].type, "length", None) for name in ("phone", "phone2")),
        *(column.limit if column is not None else None for column in columns),
    ]
    assert all(isinstance(limit, int) and limit >= formats.MOST_CHARACTERS for limit in limits)
    longest = "+1 (###) ###-####" + " #" * 11 + "#"
    assert len(longest) == formats.MOST_CHARACTERS
    written = formats.phone("1" + "5" * 22, _patterns([longest]))
    assert written is not None
    assert len(written) == formats.MOST_CHARACTERS
    # Whatever a pattern writes, help_phone takes: the / among its marks too.
    assert product.check_phone(written) == written
    assert product.check_phone("555/010-0123") == "555/010-0123"
    assert set(formats.MARKS) <= set(product.PHONE_MARKS)


def test_a_pattern_held_from_before_its_rule_is_passed_over() -> None:
    held = formats.of(["### x ####", 12, "###-###-####"], "true")
    assert [one.text for one in held.patterns] == ["###-###-####"]
    assert held.email_lower_case is False
    assert formats.of(None, None) == formats.Formats()
    assert formats.Formats().phone("5550100123") == "5550100123"
    assert formats.Formats().email("Kim.Lee@Example.NET") == "Kim.Lee@Example.NET"


# Lists of patterns of which one writes a number in a form that another fits first, as
# the review of 0.9.18 found, beside every list of the cases.
TRICKY = (
    ["#-###-###-####", "1 (###) ###-####"],
    ["########", "1 ### ####"],
    ["+1 (###) ###-####", "###-###-####", "###-####"],
    ["(###) ###-####", "###.###.####", "1-###-###-####"],
    ["+## ### ### ####", "+1 (###) ###-####", "## ### ### ####"],
    ["1 ### ### ####", "##########", "+1 ##########", "###########"],
    ["####", "#-###", "1 ####", "+1 ####", "#####"],
)


def _numbers() -> list[str]:
    """Return what is typed in the cases and what they keep, and numbers made up of
    digits, marks and a + or a 1 before them, as many people type them."""
    found = [case[key] for case in _of("phone_formats") for key in ("typed", "kept")]
    made = random.Random(322)  # noqa: S311 - numbers for a test, not a secret
    for _ in range(600):
        digits = "".join(made.choice("0123456789") for _ in range(made.randint(4, 14)))
        parts, at = [], 0
        while at < len(digits):
            step = made.randint(1, 4)
            parts.append(digits[at : at + step])
            at += step
        joined = "".join(part + made.choice(["", " ", "-", ".", "/", ") ", " ("]) for part in parts)
        found.append(made.choice(["", "", "+", "+1 ", "1 ", "(", " "]) + joined.rstrip())
    return found


def test_a_number_formatted_once_is_formatted_the_same_again() -> None:
    """What the page writes as a person leaves the box is what the server saves, and an
    export loaded back changes nothing (P-322 (7), the review of 0.9.18)."""
    numbers = _numbers()
    lists = [*TRICKY, *(case["setting"] for case in _of("phone_formats"))]
    for texts in lists:
        patterns = _patterns(texts)
        for number in numbers:
            once = formats.phone(number, patterns)
            assert formats.phone(once, patterns) == once, (texts, number, once)


def test_a_number_in_the_form_of_a_pattern_is_kept_as_it_is() -> None:
    patterns = _patterns(["#-###-###-####", "1 (###) ###-####"])
    # Its characters exactly as the pattern writes them, a digit at each #.
    assert formats.phone("1 (555) 010-0123", patterns) == "1 (555) 010-0123"
    assert formats.phone("1 (555) 010-0123 ", patterns) == "1-555-010-0123"
    assert formats.phone("1 (555)010-0123", patterns) == "1-555-010-0123"
    assert formats.phone("2 (555) 010-0123", patterns) == "2-555-010-0123"


def test_blank_and_none_are_kept() -> None:
    patterns = _patterns(["###-###-####"])
    assert formats.phone(None, patterns) is None
    assert formats.phone("", patterns) == ""
    assert formats.email(None, True) is None
    assert formats.email("", True) == ""
