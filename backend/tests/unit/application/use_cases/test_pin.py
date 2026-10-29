"""The pure rules of PIN sign-in (U32): the keyed hash that is stored, the 10 minutes in which a PIN
may be set, the role and services a session carries, the throttle keys, and that a command never
shows a PIN. The flow (what is stored, read back from Neo4j) is in
tests/integration/application/test_pin.py, and the flow against stand-in ports is in
test_pin_flow.py. Sample values only: the PIN is a sample, never a real one."""

from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from diucs.application.use_cases.pin import (
    PIN_HMAC_SECRET,
    PIN_SET_WINDOW,
    RATE_WINDOW,
    SET_PIN_PER_PERSON,
    SIGN_IN_PER_DEVICE,
    SIGN_IN_PER_PERSON,
    VERIFIED_PURPOSES,
    PinSignInCommand,
    PinSignInResult,
    SetPinCommand,
    limiter_key,
    pin_hash,
    reporter_service_ids,
    session_role,
    verification_is_fresh,
)
from diucs.domain.codes import PractitionerRoleCode, Role
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.people import PractitionerRole
from diucs.domain.rules.identity_policy import PIN_MAX_TRIES, REVERIFY_EVERY

NOW = datetime(2026, 10, 29, 14, 0, tzinfo=UTC)
SECRET = b"pin-hmac-test-secret-0123456789abcdef"
PIN = "482913"


# The stored hash


def test_the_stored_value_is_a_keyed_hash_that_is_not_the_pin() -> None:
    stored = pin_hash(SECRET, "prac-1", "dev-1", PIN)

    assert len(stored) == 64
    assert all(c in "0123456789abcdef" for c in stored)
    assert PIN not in stored
    assert stored == pin_hash(SECRET, "prac-1", "dev-1", PIN)


def test_the_hash_depends_on_the_secret_the_practitioner_the_device_and_the_pin() -> None:
    base = pin_hash(SECRET, "prac-1", "dev-1", PIN)

    assert base != pin_hash(b"another-secret-0123456789abcdef-0123", "prac-1", "dev-1", PIN)
    assert base != pin_hash(SECRET, "prac-2", "dev-1", PIN)
    assert base != pin_hash(SECRET, "prac-1", "dev-2", PIN)
    assert base != pin_hash(SECRET, "prac-1", "dev-1", "482914")


def test_the_pin_of_one_device_is_not_the_hash_of_another_even_when_the_ids_run_together() -> None:
    assert pin_hash(SECRET, "ab", "c", PIN) != pin_hash(SECRET, "a", "bc", PIN)


@given(st.text(alphabet="0123456789", min_size=6, max_size=6), st.text(min_size=1, max_size=20))
def test_the_hash_is_a_stable_digest_whatever_the_ids(pin: str, ident: str) -> None:
    stored = pin_hash(SECRET, ident, "dev-1", pin)

    assert len(stored) == 64
    assert stored == pin_hash(SECRET, ident, "dev-1", pin)
    assert stored != pin_hash(SECRET, ident, "dev-2", pin)


def test_the_secret_name_is_the_one_the_spec_names() -> None:
    assert PIN_HMAC_SECRET == "pin-hmac"


# The 10 minutes in which a PIN may be set


@pytest.mark.parametrize(
    ("age", "expected"),
    [
        (timedelta(0), True),
        (timedelta(minutes=2), True),
        (timedelta(minutes=9, seconds=59), True),
        (timedelta(minutes=10), True),
        (timedelta(minutes=10, seconds=1), False),
        (timedelta(minutes=11), False),
        (timedelta(days=1), False),
    ],
)
def test_a_verification_is_fresh_for_ten_minutes_by_the_clock(
    age: timedelta, expected: bool
) -> None:
    stamp = NOW - age

    assert verification_is_fresh(stamp, stamp, NOW) is expected


def test_the_window_is_ten_minutes() -> None:
    assert timedelta(minutes=10) == PIN_SET_WINDOW


def test_a_verification_that_never_happened_or_is_in_the_future_is_not_fresh() -> None:
    assert verification_is_fresh(None, NOW, NOW) is False
    assert (
        verification_is_fresh(NOW + timedelta(seconds=1), NOW + timedelta(seconds=1), NOW) is False
    )


def test_the_caller_cannot_claim_a_fresher_verification_than_the_record_holds() -> None:
    stored = NOW - timedelta(minutes=5)

    assert verification_is_fresh(stored, stored, NOW) is True
    assert verification_is_fresh(stored, stored + timedelta(seconds=1), NOW) is False
    assert verification_is_fresh(stored, NOW, NOW) is False


def test_a_claim_that_is_older_than_the_window_is_not_fresh_even_when_the_record_is() -> None:
    stored = NOW - timedelta(minutes=1)
    claimed = NOW - timedelta(minutes=11)

    assert verification_is_fresh(stored, claimed, NOW) is False


def test_the_london_clock_change_does_not_move_the_window() -> None:
    # 01:55 BST on 2026-10-25 is 00:55 UTC; ten minutes later is 01:05 UTC, which is 01:05 GMT.
    stamp = datetime(2026, 10, 25, 0, 55, tzinfo=UTC)
    now = datetime(2026, 10, 25, 1, 5, tzinfo=UTC)

    assert verification_is_fresh(stamp, stamp, now) is True
    assert verification_is_fresh(stamp, stamp, now + timedelta(seconds=1)) is False


def test_a_naive_time_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        verification_is_fresh(datetime(2026, 10, 29, 13, 55), NOW, NOW)
    with pytest.raises(ValidationFailed):
        verification_is_fresh(NOW, datetime(2026, 10, 29, 13, 55), NOW)
    with pytest.raises(ValidationFailed):
        verification_is_fresh(NOW, NOW, datetime(2026, 10, 29, 14, 0))


def test_the_purposes_that_may_stamp_a_device_are_the_four_that_follow_a_text_code() -> None:
    assert {"setup", "pin-reset", "new-device", "reverify"} == VERIFIED_PURPOSES
    assert "register" not in VERIFIED_PURPOSES


# The role and services of a session


def _role(
    code: PractitionerRoleCode,
    service: str | None = "svc-1",
    *,
    active: bool = True,
    role_id: str = "r-1",
    start: datetime = NOW - timedelta(days=1),
    end: datetime | None = None,
) -> PractitionerRole:
    return PractitionerRole(
        id=role_id,
        practitioner_id="prac-1",
        service_id=service,
        code=code,
        active=active,
        channel=None,
        period_start=start,
        period_end=end,
    )


def test_a_reporter_post_gives_the_reporter_role() -> None:
    assert session_role([PractitionerRoleCode.DUTY_MANAGER]) is Role.REPORTER
    assert session_role([PractitionerRoleCode.COORDINATOR]) is Role.REPORTER
    assert session_role(
        [PractitionerRoleCode.CRITERIA_OWNER, PractitionerRoleCode.COORDINATOR]
    ) is (Role.REPORTER)


def test_no_reporter_post_gives_no_role_and_never_a_higher_one() -> None:
    assert session_role([]) is None
    assert session_role([PractitionerRoleCode.SHIFT_LEAD]) is None
    assert session_role([PractitionerRoleCode.CLINICAL_LEAD, PractitionerRoleCode.REVIEWER]) is None


def test_the_services_are_those_of_active_reporter_posts_in_effect_sorted_and_distinct() -> None:
    roles = [
        _role(PractitionerRoleCode.DUTY_MANAGER, "svc-b", role_id="r-b"),
        _role(PractitionerRoleCode.COORDINATOR, "svc-a", role_id="r-a"),
        _role(PractitionerRoleCode.DUTY_MANAGER, "svc-a", role_id="r-a2"),
        _role(PractitionerRoleCode.DUTY_MANAGER, "svc-c", active=False, role_id="r-c"),
        _role(PractitionerRoleCode.DUTY_MANAGER, "svc-d", start=NOW + timedelta(hours=1)),
        _role(PractitionerRoleCode.DUTY_MANAGER, "svc-e", end=NOW, role_id="r-e"),
        _role(PractitionerRoleCode.CRITERIA_OWNER, "svc-f", role_id="r-f"),
        _role(PractitionerRoleCode.DUTY_MANAGER, None, role_id="r-g"),
    ]

    assert reporter_service_ids(roles, NOW) == ("svc-a", "svc-b")


# The throttle keys


def test_a_throttle_key_names_the_kind_and_holds_no_id() -> None:
    key = limiter_key("pin-signin-device", "prac-1", "dev-1")

    assert key.startswith("pin-signin-device:")
    assert "prac-1" not in key
    assert "dev-1" not in key


def test_a_throttle_key_is_the_same_for_the_same_parts_and_differs_otherwise() -> None:
    key = limiter_key("pin-signin-device", "prac-1", "dev-1")

    assert key == limiter_key("pin-signin-device", "prac-1", "dev-1")
    assert key != limiter_key("pin-signin-device", "prac-1", "dev-2")
    assert key != limiter_key("pin-signin-device", "prac-2", "dev-1")
    assert key != limiter_key("pin-signin-person", "prac-1", "dev-1")
    assert limiter_key("k", "ab", "c") != limiter_key("k", "a", "bc")


def test_the_limits_are_set_and_the_window_is_ten_minutes() -> None:
    assert SIGN_IN_PER_DEVICE >= PIN_MAX_TRIES
    assert SIGN_IN_PER_PERSON >= SIGN_IN_PER_DEVICE
    assert SET_PIN_PER_PERSON > 0
    assert timedelta(minutes=10) == RATE_WINDOW


# Nothing shows a PIN


def test_a_command_never_shows_its_pin() -> None:
    set_pin = SetPinCommand("prac-1", "dev-1", PIN, NOW)
    sign_in = PinSignInCommand("prac-1", "dev-1", PIN)

    for command in (set_pin, sign_in):
        assert PIN not in repr(command)
        assert PIN not in str(command)
        assert "482" not in repr(command)


def test_the_policy_numbers_are_the_rule_books() -> None:
    assert PIN_MAX_TRIES == 5
    assert timedelta(days=30) == REVERIFY_EVERY


def test_a_sign_in_result_carries_no_pin_or_hash_field() -> None:
    names = set(PinSignInResult.__slots__)

    assert names == {
        "ok",
        "locked",
        "tries_left",
        "needs_text_code",
        "practitioner_id",
        "role",
        "service_ids",
    }
