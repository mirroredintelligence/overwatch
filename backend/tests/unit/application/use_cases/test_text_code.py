"""The pure rules of the text codes (U25): the purposes, the storage key, the code's digits, the
keyed hash that is stored, the resend wait and the tries that are left.
"""

import random
from datetime import UTC, datetime, timedelta

import pytest

from diucs.application.use_cases.text_code import (
    check_purpose,
    code_hash,
    code_key,
    cooldown_seconds,
    new_code,
)
from diucs.domain.errors import ValidationFailed

ISSUED = datetime(2026, 10, 29, 9, 0, tzinfo=UTC)
PHONE_HASH = "ab" * 32
SECRET = b"code-hmac-test-secret-0123456789abcdef"


class ScriptedRandom(random.Random):
    """Gives the digits it is told, one per call to randrange(10)."""

    def __init__(self, digits: list[int]) -> None:
        super().__init__(0)
        self._digits = list(digits)

    def randrange(self, start: int, stop: int | None = None, step: int = 1) -> int:
        assert (start, stop) == (0, 10), "a code draws one digit at a time from ten values"
        return self._digits.pop(0)


@pytest.mark.parametrize("purpose", ["register", "setup", "reverify", "pin-reset", "new-device"])
def test_each_named_purpose_is_accepted(purpose: str) -> None:
    assert check_purpose(purpose) == purpose


@pytest.mark.parametrize("purpose", ["", "login", "Register", "register "])
def test_any_other_purpose_is_refused(purpose: str) -> None:
    with pytest.raises(ValidationFailed) as error:
        check_purpose(purpose)
    assert error.value.field == "purpose"


def test_a_code_is_six_digits_drawn_one_digit_at_a_time() -> None:
    assert new_code(ScriptedRandom([4, 8, 2, 9, 1, 3])) == "482913"


def test_a_code_keeps_its_leading_zero() -> None:
    assert new_code(ScriptedRandom([0, 0, 7, 0, 0, 1])) == "007001"


def test_the_storage_key_is_the_phone_hash_and_the_purpose() -> None:
    assert code_key(PHONE_HASH, "register") == f"code:{PHONE_HASH}:register"


def test_another_purpose_or_phone_has_another_key() -> None:
    assert code_key(PHONE_HASH, "register") != code_key(PHONE_HASH, "setup")
    assert code_key(PHONE_HASH, "register") != code_key("cd" * 32, "register")


def test_the_stored_hash_is_not_the_code_and_depends_on_the_purpose() -> None:
    stored = code_hash(SECRET, PHONE_HASH, "register", "482913")
    assert "482913" not in stored
    assert len(stored) == 64
    assert stored == code_hash(SECRET, PHONE_HASH, "register", "482913")
    assert stored != code_hash(SECRET, PHONE_HASH, "setup", "482913")
    assert stored != code_hash(SECRET, PHONE_HASH, "register", "482914")


def test_the_stored_hash_needs_the_secret() -> None:
    assert code_hash(SECRET, PHONE_HASH, "register", "482913") != code_hash(
        b"another-secret-0123456789abcdef-0", PHONE_HASH, "register", "482913"
    )


def test_a_new_code_may_be_asked_for_at_sixty_seconds_and_not_before() -> None:
    assert cooldown_seconds(ISSUED, ISSUED + timedelta(seconds=30)) == 30
    assert cooldown_seconds(ISSUED, ISSUED + timedelta(seconds=59)) == 1
    assert cooldown_seconds(ISSUED, ISSUED + timedelta(seconds=60)) == 0
    assert cooldown_seconds(ISSUED, ISSUED + timedelta(seconds=61)) == 0


def test_a_fractional_second_still_waits_a_whole_second() -> None:
    assert cooldown_seconds(ISSUED, ISSUED + timedelta(seconds=30, milliseconds=500)) == 30
