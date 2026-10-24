"""Booking state machine and FHIR Task status mapping (D13).

Rules: docs/spec/domain-rules.md section 3.1 (states and the Task mapping) and 3.2 (transitions).
Names: docs/spec/contracts.md, rules/booking_state.py row.
"""

import dataclasses

import pytest
from hypothesis import given
from hypothesis import strategies as st

from diucs.domain.codes import BestFitNotUsedReason, BookingStatus, ReportType
from diucs.domain.errors import InvalidTransition, ValidationFailed
from diucs.domain.rules.booking_state import (
    ALLOWED,
    FhirTaskStatus,
    allowed_targets,
    from_fhir,
    is_open,
    is_terminal,
    to_fhir,
    transition,
)

ALL_STATES = list(BookingStatus)

# domain-rules.md 3.2: the only legal moves. Everything else is refused.
LEGAL_MOVES = {
    (BookingStatus.REQUESTED, BookingStatus.CONFIRMED),
    (BookingStatus.REQUESTED, BookingStatus.DECLINED),
    (BookingStatus.REQUESTED, BookingStatus.EXPIRED),
    (BookingStatus.REQUESTED, BookingStatus.CANCELLED_BEFORE),
    (BookingStatus.CONFIRMED, BookingStatus.CANCELLED_AFTER),
    (BookingStatus.CONFIRMED, BookingStatus.WITHDRAWN),
    (BookingStatus.CONFIRMED, BookingStatus.NOT_REACHED),
    (BookingStatus.CONFIRMED, BookingStatus.COMPLETED),
}

# domain-rules.md 3.1: state, Task.status, Task.businessStatus, statusReason.
SPEC_MAPPING = [
    (BookingStatus.REQUESTED, "requested", "requested", None),
    (BookingStatus.CONFIRMED, "accepted", "confirmed", None),
    (BookingStatus.DECLINED, "rejected", "declined", None),
    (BookingStatus.EXPIRED, "cancelled", "expired", "expired"),
    (BookingStatus.CANCELLED_BEFORE, "cancelled", "cancelled-before", None),
    (BookingStatus.CANCELLED_AFTER, "cancelled", "cancelled-after", None),
    (BookingStatus.WITHDRAWN, "cancelled", "withdrawn", "withdrawn"),
    (BookingStatus.NOT_REACHED, "failed", "not-reached", None),
    (BookingStatus.COMPLETED, "completed", "completed", None),
]


@pytest.mark.parametrize(("state", "status", "business", "reason"), SPEC_MAPPING)
def test_to_fhir_follows_the_spec_table(
    state: BookingStatus, status: str, business: str, reason: str | None
) -> None:
    assert to_fhir(state) == FhirTaskStatus(
        status=status, business_status=business, status_reason=reason
    )


@pytest.mark.parametrize("state", ALL_STATES)
def test_from_fhir_reads_back_every_state(state: BookingStatus) -> None:
    assert from_fhir(to_fhir(state).business_status) is state


@pytest.mark.parametrize(
    "business_status", ["rejected", "accepted", "Requested", "", "not a state"]
)
def test_from_fhir_refuses_anything_that_is_not_a_business_status(business_status: str) -> None:
    with pytest.raises(ValidationFailed):
        from_fhir(business_status)


def test_fhir_task_status_is_frozen() -> None:
    status = to_fhir(BookingStatus.REQUESTED)
    with pytest.raises(dataclasses.FrozenInstanceError):
        status.status = "accepted"  # type: ignore[misc]


@pytest.mark.parametrize(("current", "target"), sorted(LEGAL_MOVES))
def test_every_legal_move_returns_the_target(current: BookingStatus, target: BookingStatus) -> None:
    assert transition(current, target) is target


@given(current=st.sampled_from(ALL_STATES), target=st.sampled_from(ALL_STATES))
def test_transition_is_legal_exactly_when_the_rule_book_says_so(
    current: BookingStatus, target: BookingStatus
) -> None:
    if (current, target) in LEGAL_MOVES:
        assert transition(current, target) is target
    else:
        with pytest.raises(InvalidTransition):
            transition(current, target)


@pytest.mark.parametrize(
    "state",
    [
        s
        for s in ALL_STATES
        if s is not BookingStatus.REQUESTED and s is not BookingStatus.CONFIRMED
    ],
)
def test_terminal_states_refuse_every_move(state: BookingStatus) -> None:
    for target in ALL_STATES:
        with pytest.raises(InvalidTransition):
            transition(state, target)


def test_a_state_cannot_move_to_itself() -> None:
    for state in ALL_STATES:
        with pytest.raises(InvalidTransition):
            transition(state, state)


def test_a_confirmed_booking_cannot_go_back_to_requested() -> None:
    with pytest.raises(InvalidTransition):
        transition(BookingStatus.CONFIRMED, BookingStatus.REQUESTED)


def test_a_member_of_another_enum_with_the_same_value_is_not_a_booking_status() -> None:
    # ReportType.CONFIRMED == BookingStatus.CONFIRMED is True (StrEnum, same string value).
    # A lookup keyed by the member alone would accept it. It must not.
    assert ReportType.CONFIRMED == BookingStatus.CONFIRMED
    with pytest.raises(InvalidTransition):
        transition(BookingStatus.REQUESTED, ReportType.CONFIRMED)  # type: ignore[arg-type]
    with pytest.raises(InvalidTransition):
        transition(ReportType.CONFIRMED, BookingStatus.COMPLETED)  # type: ignore[arg-type]


def test_to_fhir_refuses_a_member_of_another_enum_with_the_same_value() -> None:
    assert BestFitNotUsedReason.DECLINED == BookingStatus.DECLINED
    with pytest.raises(ValidationFailed):
        to_fhir(BestFitNotUsedReason.DECLINED)  # type: ignore[arg-type]


def test_allowed_table_has_a_row_for_every_state() -> None:
    assert set(ALLOWED) == set(BookingStatus)


@pytest.mark.parametrize("state", ALL_STATES)
def test_allowed_targets_matches_the_legal_moves(state: BookingStatus) -> None:
    expected = {target for (current, target) in LEGAL_MOVES if current is state}
    assert allowed_targets(state) == frozenset(expected)


@pytest.mark.parametrize("state", ALL_STATES)
def test_only_requested_is_open(state: BookingStatus) -> None:
    assert is_open(state) is (state is BookingStatus.REQUESTED)


@pytest.mark.parametrize("state", ALL_STATES)
def test_terminal_means_no_move_out(state: BookingStatus) -> None:
    assert is_terminal(state) is (not allowed_targets(state))


def test_confirmed_is_not_terminal_and_requested_is_not_terminal() -> None:
    assert not is_terminal(BookingStatus.REQUESTED)
    assert not is_terminal(BookingStatus.CONFIRMED)
