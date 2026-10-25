"""Booking rules around the state machine (D14).

Rules: docs/spec/domain-rules.md section 3.2. Names: docs/spec/contracts.md, rules/booking_rules.py row.
Decisions: DEC-016 (references match exactly, never by prefix).
"""

import random
from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from diucs.domain.codes import BookingStatus
from diucs.domain.errors import Conflict
from diucs.domain.rules.booking_rules import (
    BOOKING_REPLY_WINDOW,
    PHONE_PROMPT_AFTER,
    REFERENCE_ATTEMPTS,
    AskWhichReference,
    NoOpenBooking,
    OpenBookingRef,
    booking_reply_by,
    can_request,
    match_reply,
    new_reference,
    phone_prompt_at,
)

REQUESTED_AT = datetime(2026, 10, 23, 13, 16, tzinfo=UTC)


def booking(booking_id: str, reference: str, service_id: str) -> OpenBookingRef:
    return OpenBookingRef(booking_id=booking_id, reference=reference, service_id=service_id)


# Constants: domain-rules.md 3.2 (10 minutes, phone prompt at 5 minutes) and DEC-007 (4 digits).


def test_the_reply_window_and_phone_prompt_are_the_rule_book_values() -> None:
    assert BOOKING_REPLY_WINDOW == timedelta(minutes=10)
    assert PHONE_PROMPT_AFTER == timedelta(minutes=5)
    assert REFERENCE_ATTEMPTS == 50


def test_the_phone_prompt_comes_before_the_reply_by_time() -> None:
    assert timedelta(0) < PHONE_PROMPT_AFTER < BOOKING_REPLY_WINDOW


# 1. Timers


def test_requested_at_1316_utc_has_reply_by_1326_and_phone_prompt_1321() -> None:
    assert booking_reply_by(REQUESTED_AT) == datetime(2026, 10, 23, 13, 26, tzinfo=UTC)
    assert phone_prompt_at(REQUESTED_AT) == datetime(2026, 10, 23, 13, 21, tzinfo=UTC)


def test_requested_at_1416_prompts_at_1421_and_expires_at_1426() -> None:
    requested = datetime(2026, 10, 23, 14, 16, tzinfo=UTC)
    assert phone_prompt_at(requested) == datetime(2026, 10, 23, 14, 21, tzinfo=UTC)
    assert booking_reply_by(requested) == datetime(2026, 10, 23, 14, 26, tzinfo=UTC)


@given(
    requested=st.datetimes(
        min_value=datetime(2000, 1, 1),
        max_value=datetime(2100, 1, 1),
        timezones=st.just(UTC),
    )
)
def test_timers_are_fixed_offsets_from_the_request_for_any_instant(requested: datetime) -> None:
    assert booking_reply_by(requested) - requested == BOOKING_REPLY_WINDOW
    assert phone_prompt_at(requested) - requested == PHONE_PROMPT_AFTER


def test_timers_are_instants_across_the_london_clock_change() -> None:
    # The UK clock changes at 01:00 UTC on 2026-03-29. Timers are plain instant offsets, so the
    # change must not shift them. Lesson L4: compare instants, never local wall-clock times.
    requested = datetime(2026, 3, 29, 0, 55, tzinfo=UTC)
    assert booking_reply_by(requested) == datetime(2026, 3, 29, 1, 5, tzinfo=UTC)
    assert phone_prompt_at(requested) == datetime(2026, 3, 29, 1, 0, tzinfo=UTC)


# 2. One open request per service


def test_a_service_with_no_bookings_can_take_a_request() -> None:
    assert can_request([]) is True


@pytest.mark.parametrize(
    "statuses",
    [
        [BookingStatus.CONFIRMED, BookingStatus.DECLINED],
        [BookingStatus.EXPIRED, BookingStatus.CANCELLED_BEFORE, BookingStatus.COMPLETED],
    ],
)
def test_a_service_with_only_answered_or_closed_bookings_can_take_a_request(
    statuses: list[BookingStatus],
) -> None:
    assert can_request(statuses) is True


def test_a_service_with_a_requested_booking_cannot_take_another() -> None:
    assert can_request([BookingStatus.REQUESTED]) is False


def test_one_open_booking_blocks_a_request_among_closed_ones() -> None:
    assert can_request([BookingStatus.CONFIRMED, BookingStatus.REQUESTED]) is False


# 3 and 4. References: 4 digits, seeded, retried on collision


def test_a_new_reference_is_four_digits_between_1000_and_9999() -> None:
    reference = new_reference(random.Random(42), set())
    assert len(reference) == 4
    assert reference.isdecimal()
    assert "1000" <= reference <= "9999"


def test_the_same_seed_gives_the_same_reference() -> None:
    assert new_reference(random.Random(42), set()) == new_reference(random.Random(42), set())


def test_a_taken_reference_is_not_returned_again() -> None:
    first = new_reference(random.Random(42), set())
    second = new_reference(random.Random(42), {first})
    assert second != first
    assert len(second) == 4


@given(seed=st.integers(min_value=0, max_value=2**32 - 1))
def test_any_seed_gives_a_four_digit_reference_without_a_leading_zero(seed: int) -> None:
    reference = new_reference(random.Random(seed), set())
    assert reference.isdecimal()
    assert len(reference) == 4
    assert reference[0] != "0"


def test_a_reference_is_never_one_of_the_taken_values() -> None:
    taken = {str(n) for n in range(1000, 1500)}
    for seed in range(200):
        assert new_reference(random.Random(seed), taken) not in taken


# 5. Collisions exhaust the attempts


def test_every_reference_taken_raises_conflict() -> None:
    taken = {str(n) for n in range(1000, 10000)}
    assert len(taken) == 9000
    with pytest.raises(Conflict):
        new_reference(random.Random(42), taken)


# 6 to 8. Matching a text reply


def test_no_open_booking_and_no_reference_is_no_open_booking() -> None:
    assert match_reply([], None) == NoOpenBooking()


def test_no_open_booking_and_a_reference_is_no_open_booking() -> None:
    assert match_reply([], "4821") == NoOpenBooking()


def test_one_open_booking_without_a_reference_is_that_booking() -> None:
    only = booking("b1", "4821", "ucr-west")
    assert match_reply([only], None) == only


def test_one_open_booking_with_its_reference_is_that_booking() -> None:
    only = booking("b1", "4821", "ucr-west")
    assert match_reply([only], "4821") == only


def test_one_open_booking_with_another_reference_is_no_open_booking() -> None:
    only = booking("b1", "4821", "ucr-west")
    assert match_reply([only], "9999") == NoOpenBooking()


def test_two_open_bookings_without_a_reference_ask_which_one_in_ascending_order() -> None:
    east = booking("b1", "4821", "ucr-east")
    west = booking("b2", "3170", "ucr-west")
    assert match_reply([east, west], None) == AskWhichReference(("3170", "4821"))


def test_two_open_bookings_with_a_reference_match_that_one() -> None:
    east = booking("b1", "4821", "ucr-east")
    west = booking("b2", "3170", "ucr-west")
    assert match_reply([east, west], "3170") == west


# Beyond the prompt: DEC-016 says a reference matches exactly, never by prefix.


@pytest.mark.parametrize("reply", ["482", "48", "48211"])
def test_a_reference_that_is_a_prefix_or_extension_of_an_open_one_does_not_match(
    reply: str,
) -> None:
    only = booking("b1", "4821", "ucr-west")
    assert match_reply([only], reply) == NoOpenBooking()


def test_an_exact_reference_does_not_match_when_another_open_one_shares_its_prefix() -> None:
    long_one = booking("b1", "48211", "ucr-east")
    short_one = booking("b2", "4821", "ucr-west")
    assert match_reply([long_one, short_one], "4821") == short_one
    assert match_reply([long_one], "4821") == NoOpenBooking()


def test_a_reference_matching_none_of_several_open_bookings_is_no_open_booking() -> None:
    east = booking("b1", "4821", "ucr-east")
    west = booking("b2", "3170", "ucr-west")
    assert match_reply([east, west], "9999") == NoOpenBooking()
