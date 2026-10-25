"""Tests for diucs.domain.rules.identity_policy: text codes, PINs and re-verification (D27).

Rules: docs/spec/domain-rules.md section 7 and the D27 prompt. Times are UTC unless a test says
otherwise. The London-zoned tests cross the autumn clock change on 2026-10-25, where the same
zone's wall-clock arithmetic differs from the real instant difference (lesson L52).
The PIN values in this file are test samples only. DEC-044 records the choices the prompt
leaves open.
"""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given
from hypothesis import strategies as st

from diucs.domain.errors import DomainError, ValidationFailed
from diucs.domain.rules.identity_policy import (
    CODE_MAX_TRIES,
    CODE_RESEND_AFTER,
    CODE_VALID_FOR,
    PIN_MAX_TRIES,
    REVERIFY_EVERY,
    CodeOutcome,
    CodeState,
    PinOutcome,
    PinState,
    can_resend,
    code_attempt,
    needs_reverification,
    pin_attempt,
    reset_pin_state,
    validate_pin_format,
)

LONDON = ZoneInfo("Europe/London")


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


ISSUED = utc(2026, 10, 26, 9, 0, 0)


def fresh_code() -> CodeState:
    return CodeState(issued_at=ISSUED)


def wrong_then(state: CodeState, times: int, now: datetime) -> CodeState:
    for _ in range(times):
        state = code_attempt(state, entered_ok=False, now=now)
    return state


def test_constants_match_the_rule_book() -> None:
    assert timedelta(minutes=10) == CODE_VALID_FOR
    assert CODE_MAX_TRIES == 5
    assert timedelta(seconds=60) == CODE_RESEND_AFTER
    assert PIN_MAX_TRIES == 5
    assert timedelta(days=30) == REVERIFY_EVERY


# 1. Code validity window


def test_code_entered_just_before_ten_minutes_is_verified() -> None:
    state = code_attempt(fresh_code(), entered_ok=True, now=utc(2026, 10, 26, 9, 9, 59))
    assert state.verified is True
    assert state.last_outcome is CodeOutcome.VERIFIED


def test_code_entered_at_ten_minutes_is_expired() -> None:
    state = code_attempt(fresh_code(), entered_ok=True, now=utc(2026, 10, 26, 9, 10, 0))
    assert state.verified is False
    assert state.last_outcome is CodeOutcome.EXPIRED
    assert state.failed_tries == 0


def test_expired_attempt_leaves_the_try_count_unchanged() -> None:
    state = wrong_then(fresh_code(), 2, now=utc(2026, 10, 26, 9, 1, 0))
    later = code_attempt(state, entered_ok=False, now=utc(2026, 10, 26, 9, 10, 0))
    assert later.failed_tries == 2
    assert later.last_outcome is CodeOutcome.EXPIRED


def test_expiry_is_judged_on_the_real_instant_across_the_clock_change() -> None:
    # Issued at 00:55Z, which is London 01:55 BST. Ten minutes later is 01:05Z, which is London
    # 01:05 GMT on the second pass through 01:00. Wall-clock arithmetic would wrongly say 02:05.
    issued = datetime(2026, 10, 25, 0, 55, tzinfo=UTC).astimezone(LONDON)
    state = CodeState(issued_at=issued)
    now = datetime(2026, 10, 25, 1, 5, tzinfo=UTC).astimezone(LONDON)
    result = code_attempt(state, entered_ok=True, now=now)
    assert result.last_outcome is CodeOutcome.EXPIRED
    assert result.verified is False


# 2. Try counting


def test_four_wrong_then_right_is_verified_with_four_tries() -> None:
    state = wrong_then(fresh_code(), 4, now=utc(2026, 10, 26, 9, 1, 0))
    assert state.failed_tries == 4
    assert state.last_outcome is CodeOutcome.WRONG
    state = code_attempt(state, entered_ok=True, now=utc(2026, 10, 26, 9, 2, 0))
    assert state.verified is True
    assert state.failed_tries == 4
    assert state.last_outcome is CodeOutcome.VERIFIED


def test_fifth_wrong_try_gives_too_many_tries() -> None:
    state = wrong_then(fresh_code(), 4, now=utc(2026, 10, 26, 9, 1, 0))
    state = code_attempt(state, entered_ok=False, now=utc(2026, 10, 26, 9, 2, 0))
    assert state.failed_tries == 5
    assert state.last_outcome is CodeOutcome.TOO_MANY_TRIES
    assert state.verified is False


def test_a_sixth_correct_attempt_is_still_too_many_tries() -> None:
    state = wrong_then(fresh_code(), 5, now=utc(2026, 10, 26, 9, 1, 0))
    state = code_attempt(state, entered_ok=True, now=utc(2026, 10, 26, 9, 2, 0))
    assert state.verified is False
    assert state.last_outcome is CodeOutcome.TOO_MANY_TRIES


def test_a_wrong_try_before_the_fifth_is_a_plain_wrong() -> None:
    state = wrong_then(fresh_code(), 3, now=utc(2026, 10, 26, 9, 1, 0))
    assert state.last_outcome is CodeOutcome.WRONG
    assert state.failed_tries == 3


# 3. A verified code cannot be used again


def test_a_verified_code_used_again_is_expired() -> None:
    state = code_attempt(fresh_code(), entered_ok=True, now=utc(2026, 10, 26, 9, 1, 0))
    again = code_attempt(state, entered_ok=True, now=utc(2026, 10, 26, 9, 2, 0))
    assert again.last_outcome is CodeOutcome.EXPIRED
    assert again.verified is True


def test_a_wrong_entry_against_a_verified_code_does_not_count_as_a_try() -> None:
    state = code_attempt(fresh_code(), entered_ok=True, now=utc(2026, 10, 26, 9, 1, 0))
    again = code_attempt(state, entered_ok=False, now=utc(2026, 10, 26, 9, 2, 0))
    assert again.last_outcome is CodeOutcome.EXPIRED
    assert again.failed_tries == 0


# 4. Resend cooldown


def test_resend_is_refused_before_sixty_seconds() -> None:
    assert can_resend(utc(2026, 10, 26, 9, 0, 0), utc(2026, 10, 26, 9, 0, 59)) is False


def test_resend_is_allowed_at_sixty_seconds() -> None:
    assert can_resend(utc(2026, 10, 26, 9, 0, 0), utc(2026, 10, 26, 9, 1, 0)) is True


def test_resend_is_refused_when_the_clock_has_gone_backwards() -> None:
    # Fail closed: a last-sent time in the future is not a reason to send another code.
    assert can_resend(utc(2026, 10, 26, 9, 5, 0), utc(2026, 10, 26, 9, 0, 0)) is False


# 5. PIN attempts


def test_four_wrong_pins_then_ok_resets_the_count() -> None:
    state = PinState()
    for _ in range(4):
        state = pin_attempt(state, ok=False, now=ISSUED)
    assert state.failed_tries == 4
    assert state.locked is False
    state = pin_attempt(state, ok=True, now=ISSUED)
    assert state.failed_tries == 0
    assert state.locked is False
    assert state.last_outcome is PinOutcome.OK


def test_five_wrong_pins_lock_the_pin() -> None:
    state = PinState()
    for _ in range(5):
        state = pin_attempt(state, ok=False, now=ISSUED)
    assert state.locked is True
    assert state.failed_tries == 5
    assert state.last_outcome is PinOutcome.LOCKED


def test_a_correct_pin_while_locked_stays_locked() -> None:
    locked = PinState(failed_tries=5, locked=True)
    state = pin_attempt(locked, ok=True, now=ISSUED)
    assert state.locked is True
    assert state.last_outcome is PinOutcome.LOCKED
    assert state.failed_tries == 5


def test_a_wrong_pin_while_locked_stays_locked_and_does_not_count() -> None:
    locked = PinState(failed_tries=5, locked=True)
    state = pin_attempt(locked, ok=False, now=ISSUED)
    assert state.locked is True
    assert state.failed_tries == 5
    assert state.last_outcome is PinOutcome.LOCKED


def test_reset_pin_state_unlocks_and_clears_the_count() -> None:
    assert reset_pin_state() == PinState()
    assert reset_pin_state().locked is False
    assert reset_pin_state().failed_tries == 0


# 6. PIN format


@pytest.mark.parametrize("pin", ["123456", "000000", "904172"])
def test_six_ascii_digits_are_a_valid_pin_format(pin: str) -> None:
    validate_pin_format(pin)


@pytest.mark.parametrize(
    "pin",
    [
        "12345",
        "1234567",
        "12a456",
        "１２３４５６",  # full-width digits
        "",
        "12 456",
        "١٢٣٤٥٦",  # Arabic-Indic digits
        "123456\n",
    ],
)
def test_anything_else_is_refused(pin: str) -> None:
    with pytest.raises(ValidationFailed) as raised:
        validate_pin_format(pin)
    assert raised.value.field == "pin"


def test_the_refusal_never_echoes_the_pin() -> None:
    with pytest.raises(ValidationFailed) as raised:
        validate_pin_format("12a456")
    assert "12a456" not in str(raised.value)
    assert "12a456" not in raised.value.message


# 7. Re-verification


def test_unknown_device_needs_reverification_even_when_just_verified() -> None:
    assert needs_reverification(utc(2026, 10, 26, 9, 0, 0), utc(2026, 10, 26, 9, 1, 0), False)


def test_never_verified_needs_reverification() -> None:
    assert needs_reverification(None, utc(2026, 10, 26, 9, 0, 0), True)


def test_twenty_nine_days_twenty_three_hours_does_not_need_reverification() -> None:
    last = utc(2026, 9, 26, 9, 0, 0)
    now = last + timedelta(days=29, hours=23)
    assert needs_reverification(last, now, True) is False


def test_exactly_thirty_days_needs_reverification() -> None:
    last = utc(2026, 9, 26, 9, 0, 0)
    assert needs_reverification(last, last + timedelta(days=30), True) is True


def test_thirty_days_is_counted_on_the_real_instant_across_the_clock_change() -> None:
    # 30 real days from 11:30Z on 2026-09-25 is 11:30Z on 2026-10-25. In London the wall clock
    # moves from 12:30 BST to 11:30 GMT, so a wall-clock difference is 29 days 23 hours.
    last = datetime(2026, 9, 25, 11, 30, tzinfo=UTC).astimezone(LONDON)
    now = datetime(2026, 10, 25, 11, 30, tzinfo=UTC).astimezone(LONDON)
    assert needs_reverification(last, now, True) is True


def test_a_verification_stamped_in_the_future_needs_reverification() -> None:
    # Fail closed on a clock that has gone backwards.
    assert needs_reverification(utc(2026, 10, 27, 9, 0, 0), utc(2026, 10, 26, 9, 0, 0), True)


def test_naive_datetimes_are_refused() -> None:
    naive = datetime(2026, 10, 26, 9, 0, 0)
    with pytest.raises(DomainError):
        code_attempt(CodeState(issued_at=naive), entered_ok=True, now=ISSUED)
    with pytest.raises(DomainError):
        can_resend(naive, ISSUED)
    with pytest.raises(DomainError):
        needs_reverification(naive, ISSUED, True)


# Property tests: fail closed


@given(
    st.lists(st.booleans(), min_size=0, max_size=12),
    st.integers(min_value=0, max_value=1200),
)
def test_a_code_is_never_verified_after_it_expires(attempts: list[bool], seconds: int) -> None:
    state = fresh_code()
    now = ISSUED + timedelta(seconds=seconds)
    for ok in attempts:
        state = code_attempt(state, entered_ok=ok, now=now)
    if seconds >= 600:
        assert state.verified is False


@given(st.lists(st.booleans(), min_size=0, max_size=20))
def test_a_locked_pin_never_unlocks_without_a_reset(attempts: list[bool]) -> None:
    state = PinState()
    seen_locked = False
    for ok in attempts:
        state = pin_attempt(state, ok=ok, now=ISSUED)
        seen_locked = seen_locked or state.locked
        if seen_locked:
            assert state.locked is True


@given(st.lists(st.booleans(), min_size=0, max_size=20))
def test_a_code_is_never_verified_from_wrong_entries_alone(attempts: list[bool]) -> None:
    state = fresh_code()
    now = ISSUED + timedelta(seconds=1)
    for ok in attempts:
        state = code_attempt(state, entered_ok=ok, now=now)
    if not any(attempts):
        assert state.verified is False


@given(st.text(max_size=12))
def test_validate_pin_format_accepts_exactly_six_ascii_digits(pin: str) -> None:
    valid = len(pin) == 6 and all(c in "0123456789" for c in pin)
    if valid:
        validate_pin_format(pin)
    else:
        with pytest.raises(ValidationFailed):
            validate_pin_format(pin)


# Fail closed on a clock that has gone backwards (added after the first red commit)


def test_a_code_stamped_in_the_future_is_expired() -> None:
    state = CodeState(issued_at=utc(2026, 10, 26, 9, 5, 0))
    result = code_attempt(state, entered_ok=True, now=utc(2026, 10, 26, 9, 0, 0))
    assert result.verified is False
    assert result.last_outcome is CodeOutcome.EXPIRED


# Regression pins for the spring clock change, 2026-03-29 (not red: the code is already correct)
# London goes from 01:00 GMT straight to 02:00 BST, so wall-clock arithmetic on the same zone
# would run an hour fast across this day. These pin the real-instant behaviour.


def test_spring_clock_code_is_still_valid_one_minute_before_ten_minutes() -> None:
    # Issued 00:55Z (London 00:55 GMT). Expiry is 01:05Z. At 01:04Z the code is still valid.
    issued = datetime(2026, 3, 29, 0, 55, tzinfo=UTC).astimezone(LONDON)
    now = datetime(2026, 3, 29, 1, 4, tzinfo=UTC).astimezone(LONDON)
    result = code_attempt(CodeState(issued_at=issued), entered_ok=True, now=now)
    assert result.verified is True
    assert result.last_outcome is CodeOutcome.VERIFIED


def test_spring_clock_code_expires_at_exactly_ten_real_minutes() -> None:
    issued = datetime(2026, 3, 29, 0, 55, tzinfo=UTC).astimezone(LONDON)
    now = datetime(2026, 3, 29, 1, 5, tzinfo=UTC).astimezone(LONDON)
    result = code_attempt(CodeState(issued_at=issued), entered_ok=True, now=now)
    assert result.verified is False
    assert result.last_outcome is CodeOutcome.EXPIRED


def test_spring_clock_29_days_23h59m_does_not_need_reverification() -> None:
    # Last verified 2026-02-27 12:30Z (GMT). 29 days 23 h 59 min later is 12:29Z on 2026-03-29.
    # Wall-clock arithmetic would count the spring hour and say 30 days.
    last = datetime(2026, 2, 27, 12, 30, tzinfo=UTC).astimezone(LONDON)
    now = datetime(2026, 3, 29, 12, 29, tzinfo=UTC).astimezone(LONDON)
    assert needs_reverification(last, now, True) is False


def test_spring_clock_exactly_thirty_real_days_needs_reverification() -> None:
    last = datetime(2026, 2, 27, 12, 30, tzinfo=UTC).astimezone(LONDON)
    now = datetime(2026, 3, 29, 12, 30, tzinfo=UTC).astimezone(LONDON)
    assert needs_reverification(last, now, True) is True
