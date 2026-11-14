"""Roles, access codes, tokens and the throttle, each by itself."""

from pathlib import Path

import pytest
from argon2 import PasswordHasher, extract_parameters

from hirdir import clock
from hirdir.auth import codes, tokens
from hirdir.auth.roles import Role, highest
from hirdir.auth.throttle import Throttle
from hirdir.ids import is_hid, new_hid


def test_hid_is_a_version_7_uuid_in_canonical_text() -> None:
    hid = new_hid()
    assert is_hid(hid)
    assert hid[14] == "7"
    assert not is_hid(hid.upper())
    assert not is_hid("not-an-id")


def test_highest_role_wins() -> None:
    assert highest(["viewer", "admin", "inventory"]) is Role.ADMIN
    assert highest(["viewer"]) is Role.VIEWER
    assert highest([]) is None
    assert Role.ADMIN.allows(Role.INVENTORY)
    assert not Role.VIEWER.allows(Role.INVENTORY)


def test_generated_code_is_three_groups_of_four() -> None:
    code = codes.generate()
    assert [len(part) for part in code.split("-")] == [4, 4, 4]
    assert code != codes.generate()


def test_code_verifies_only_against_its_own_hash() -> None:
    stored = codes.hash_code("river-stone")
    assert "river-stone" not in stored
    assert codes.verify(stored, "river-stone")
    assert not codes.verify(stored, "river-stonE")
    assert not codes.verify(None, "river-stone")
    assert not codes.verify("not a hash", "river-stone")


def test_a_code_is_hashed_at_the_cost_the_library_recommends(full_cost: PasswordHasher) -> None:
    # The other tests hash cheaply, to save time. What is released does not.
    stored = codes.hash_code("river-stone")

    assert stored.startswith("$argon2id$")
    told = extract_parameters(stored)
    assert (told.time_cost, told.memory_cost, told.parallelism) == (
        full_cost.time_cost,
        full_cost.memory_cost,
        full_cost.parallelism,
    )
    assert told.memory_cost >= 19 * 1024
    assert codes.verify(stored, "river-stone")
    assert not codes.verify(None, "river-stone")


def test_signing_key_is_created_once_and_private(tmp_path: Path) -> None:
    path = tmp_path / "secret.key"
    key = tokens.load_or_create_key(path)
    assert len(key) == tokens.KEY_BYTES
    assert path.stat().st_mode & 0o777 == 0o600
    assert tokens.load_or_create_key(path) == key


def test_session_token_round_trip_and_tamper() -> None:
    key, other = b"k" * 32, b"x" * 32
    issued = clock.now_ms()
    token, expires_at = tokens.issue_session(key, "user-1", issued, hours=12)
    claims = tokens.read_session(key, token)
    assert (claims.user_hid, claims.issued_ms) == ("user-1", issued)
    assert claims.expires_at == expires_at
    with pytest.raises(tokens.InvalidToken):
        tokens.read_session(other, token)
    with pytest.raises(tokens.InvalidToken):
        tokens.read_session(key, token[:-2] + "aa")


def test_expired_session_token_is_refused() -> None:
    key = b"k" * 32
    long_ago = clock.now_ms() - 13 * 3600 * 1000
    token, _ = tokens.issue_session(key, "user-1", long_ago, hours=12)
    with pytest.raises(tokens.InvalidToken):
        tokens.read_session(key, token)


def test_unsigned_token_is_refused() -> None:
    import jwt

    forged = jwt.encode({"sub": "user-1", "exp": 9999999999, "ims": 1}, "", algorithm="none")
    with pytest.raises(tokens.InvalidToken):
        tokens.read_session(b"k" * 32, forged)


def test_service_token_is_stored_as_a_hash() -> None:
    secret, stored = tokens.new_service_token()
    assert tokens.is_service_token(secret)
    assert stored == tokens.hash_service_token(secret)
    assert secret not in stored


def test_throttle_delays_after_the_threshold_and_doubles() -> None:
    now = [100.0]
    throttle = Throttle(threshold=5, clock=lambda: now[0])
    for _ in range(4):
        throttle.failure("user:ada")
    assert throttle.retry_after("user:ada") == 0
    throttle.failure("user:ada")
    assert throttle.retry_after("user:ada") == 1
    assert throttle.retry_after("user:someone-else") == 0
    now[0] += 1
    assert throttle.retry_after("user:ada") == 0
    throttle.failure("user:ada")
    assert throttle.retry_after("user:ada") == 2
    for _ in range(20):
        throttle.failure("user:ada")
    assert throttle.retry_after("user:ada") == 300
    throttle.success("user:ada")
    assert throttle.retry_after("user:ada") == 0


def test_throttle_takes_the_longest_wait_of_its_keys() -> None:
    now = [0.0]
    throttle = Throttle(threshold=1, clock=lambda: now[0])
    throttle.failure("addr:192.0.2.1")
    assert throttle.retry_after("user:new", "addr:192.0.2.1") == 1
