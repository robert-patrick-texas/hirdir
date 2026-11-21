"""The commands that retire a user, a contact or an operator and bring a user back
(P-296 to P-298), run against the application itself."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.api import test_cli
from tests.api.inventory import Maker
from tests.api.test_person_retired import Kim

# The fixture that runs `hirdir` against the test client, as the Inventory user.
run = test_cli.run


@pytest.fixture
def desk(client: TestClient, admin: dict[str, str]) -> Maker:
    return Maker(client, admin)


@pytest.fixture
def kim(desk: Maker) -> Kim:
    return Kim(desk)


@pytest.fixture
def as_admin(admin: dict[str, str]) -> tuple[str, str]:
    """The option that runs a command as the Admin."""
    return ("--token", admin["Authorization"].removeprefix("Bearer "))


def _chain(output: str) -> list[list[str]]:
    """The lines of the chain a command printed: the kind, what it is known by, its fate."""
    lines = [line for line in output.splitlines() if line.startswith("  ")]
    return [[line.split()[0], line.split()[1], line[62:].strip()] for line in lines]


def test_users_list_leaves_the_retired_out_until_they_are_asked_for(
    run: Any, kim: Kim, as_admin: tuple[str, str]
) -> None:
    kim.retire("users", kim.user, contact="keep", operators=kim.every("keep"))

    def listed(*options: str) -> dict[str, str]:
        lines = run("users", "list", *options, *as_admin).stdout.splitlines()[1:]
        return {line.split()[0]: line[44:54].strip() for line in lines}

    assert listed() == {"ada": "active", "ivy": "active", "vic": "active"}
    assert listed("--retired") == {
        "ada": "active",
        "ivy": "active",
        "klee": "retired",
        "vic": "active",
    }
    assert listed("--retired-only") == {"klee": "retired"}


def test_a_dry_run_prints_what_is_linked_and_the_plan_and_sends_nothing(
    run: Any, kim: Kim, desk: Maker, as_admin: tuple[str, str]
) -> None:
    before = desk.get("/audit-events", limit=1)["total"]
    said = run("contacts", "retire", "kim.lee@example.com", "--dry-run").stdout
    assert said.splitlines()[0] == "contact Kim Lee, and what is linked to it:"
    assert _chain(said) == [
        ["operator", "KL", "not said"],
        ["operator", "LM", "not said"],
        ["contact", "Kim", "retire"],
        ["user", "klee", "not said"],
    ]
    assert said.splitlines()[-1] == "nothing was sent: this is what would be done"
    said = run(
        "contacts",
        "retire",
        "kim.lee@example.com",
        "--user",
        "retire",
        "--operator",
        "KL=hand_over:sam.okafor@example.net",
        "--operator",
        "lm=retire",
        "--dry-run",
    ).stdout
    assert _chain(said) == [
        ["operator", "KL", "hand over to sam.okafor@example.net"],
        ["operator", "LM", "retire"],
        ["contact", "Kim", "retire"],
        ["user", "klee", "retire"],
    ]
    assert kim.statuses() == {"KL": "active", "LM": "active", "contact": "active", "user": "active"}
    assert desk.get("/audit-events", limit=1)["total"] == before
    # What an option cannot say is refused before anything is asked of the server.
    run("contacts", "retire", "kim.lee@example.com", "--user", "maybe", "--dry-run", expect=2)
    run("contacts", "retire", "kim.lee@example.com", "--operator", "KL=sell", expect=2)
    run("contacts", "retire", "kim.lee@example.com", "--operator", "KL=hand_over", expect=2)
    run("contacts", "retire", "nobody@example.com", expect=4)


def test_a_contact_is_retired_with_what_the_options_say_of_the_rest(
    run: Any, kim: Kim, desk: Maker, as_admin: tuple[str, str]
) -> None:
    # Saying nothing of the rest is refused by the server, which names each.
    refused = run("contacts", "retire", "kim.lee@example.com", expect=5)
    assert "linked.user" in refused.output
    assert "linked.operators" in refused.output
    # The Inventory user does not retire an account.
    options = (
        "--user",
        "retire",
        "--operator",
        "KL=hand_over:Sam Okafor",
        "--operator",
        "LM=retire",
    )
    run("contacts", "retire", "kim.lee@example.com", *options, expect=3)
    done = run("contacts", "retire", "kim.lee@example.com", *options, *as_admin).stdout
    assert done.splitlines()[-1] == "Kim Lee is retired"
    assert kim.statuses() == {"LM": "retired", "contact": "retired", "user": "retired"}
    assert desk.get(f"/operators/{kim.kl['hid']}")["contact_hid"] == kim.sam["hid"]


def test_a_user_is_retired_and_brought_back_from_the_command_line(
    run: Any, kim: Kim, desk: Maker, as_admin: tuple[str, str]
) -> None:
    run("users", "retire", "klee", "--contact", "retire", expect=3)
    refused = run("users", "retire", "klee", "--contact", "retire", *as_admin, expect=5)
    assert "linked.operators" in refused.output
    done = run(
        "users",
        "retire",
        "klee",
        "--contact",
        "retire",
        "--operator",
        "KL=open",
        "--operator",
        "LM=retire",
        *as_admin,
    ).stdout
    assert done.splitlines()[-1] == "klee is retired"
    assert kim.statuses() == {"LM": "retired", "contact": "retired", "user": "retired"}
    run("users", "retire", "nobody", *as_admin, expect=4)

    # Brought back: alone it is refused, its contact being retired; with it, a new code.
    planned = run("users", "bring-back", "klee", "--contact", "--dry-run", *as_admin).stdout
    assert planned.splitlines()[-1] == "nothing was sent: this is what would be done"
    assert kim.statuses()["user"] == "retired"
    refused = run("users", "bring-back", "klee", *as_admin, expect=5)
    assert "linked.contact" in refused.output
    run("users", "bring-back", "klee", "--contact", expect=3)
    back = run(
        "users", "bring-back", "klee", "--contact", "--operator", "LM", *as_admin
    ).stdout.splitlines()
    assert back[-2] == "klee is active again, with no role and no group"
    code = back[-1].removeprefix("access code, shown this once: ")
    assert kim.statuses() == {"LM": "active", "contact": "active", "user": "active"}
    signed = desk.client.post(
        "/api/v1/auth/sign-in", json={"username": "klee", "access_code": code}
    )
    assert signed.status_code == 200


def test_an_operator_is_retired_with_what_the_options_say_of_the_rest(
    run: Any, kim: Kim, desk: Maker
) -> None:
    refused = run("operators", "retire", "LM", expect=5)
    assert "linked.contact" in refused.output
    done = run(
        "operators", "retire", "LM", "--user", "keep", "--contact", "keep", "--operator", "KL=keep"
    ).stdout
    assert _chain(done) == [
        ["operator", "KL", "keep"],
        ["operator", "LM", "retire"],
        ["contact", "Kim", "keep"],
        ["user", "klee", "keep"],
    ]
    assert done.splitlines()[-1] == "LM is released; it was on 0 records of its own"
    assert kim.statuses() == {
        "KL": "active",
        "LM": "retired",
        "contact": "active",
        "user": "active",
    }
    # `release` is the same command, as before.
    label = desk.post("/operators", {"label": "OPEN"})
    assert run("operators", "release", "OPEN").stdout.splitlines()[-1] == (
        "OPEN is released; it was on 0 records of its own"
    )
    assert desk.get(f"/operators/{label['hid']}")["record_status"] == "retired"
