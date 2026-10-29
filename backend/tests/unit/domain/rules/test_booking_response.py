"""Tests for the pure rules around a booking reply and a cancellation (U18, U20).

The reply moves a requested booking to confirmed or declined. A reply to an expired booking changes
nothing and is reported as already final. The decline reason can arrive later. Sample values only.
"""

import pytest

from diucs.domain.codes import BookingStatus, Role
from diucs.domain.errors import Conflict, InvalidTransition, ValidationFailed
from diucs.domain.messages.catalogue import MessageId
from diucs.domain.rules.booking_response import (
    advisor_may_cancel,
    cancel_target,
    echo_message,
    may_set_decline_reason,
    plan_response,
    responder_may_act,
)

SERVICE = "ucr-west"
OTHER_SERVICE = "ucr-east"


@pytest.mark.parametrize(
    ("decision", "target"),
    [("confirm", BookingStatus.CONFIRMED), ("decline", BookingStatus.DECLINED)],
)
def test_a_reply_to_a_requested_booking_moves_it_to_confirmed_or_declined(
    decision: str, target: BookingStatus
) -> None:
    assert plan_response(BookingStatus.REQUESTED, decision) is target


@pytest.mark.parametrize("decision", ["confirm", "decline"])
def test_a_reply_to_an_expired_booking_is_already_final_and_moves_nothing(decision: str) -> None:
    assert plan_response(BookingStatus.EXPIRED, decision) is None


@pytest.mark.parametrize(
    "current",
    [
        BookingStatus.CONFIRMED,
        BookingStatus.DECLINED,
        BookingStatus.CANCELLED_BEFORE,
        BookingStatus.CANCELLED_AFTER,
        BookingStatus.WITHDRAWN,
        BookingStatus.NOT_REACHED,
        BookingStatus.COMPLETED,
    ],
)
@pytest.mark.parametrize("decision", ["confirm", "decline"])
def test_a_reply_to_any_other_final_state_is_an_invalid_transition(
    current: BookingStatus, decision: str
) -> None:
    with pytest.raises(InvalidTransition):
        plan_response(current, decision)


@pytest.mark.parametrize("decision", ["maybe", "", "CONFIRM", "accept"])
def test_an_unknown_decision_is_a_validation_failure(decision: str) -> None:
    with pytest.raises(ValidationFailed):
        plan_response(BookingStatus.REQUESTED, decision)


def test_a_decline_reason_can_be_set_later_only_on_a_declined_booking_without_one() -> None:
    may_set_decline_reason(BookingStatus.DECLINED, reason_set=False)


def test_a_second_decline_reason_is_a_conflict() -> None:
    with pytest.raises(Conflict):
        may_set_decline_reason(BookingStatus.DECLINED, reason_set=True)


@pytest.mark.parametrize(
    "current", [BookingStatus.REQUESTED, BookingStatus.CONFIRMED, BookingStatus.EXPIRED]
)
def test_a_decline_reason_on_a_booking_not_declined_is_an_invalid_transition(
    current: BookingStatus,
) -> None:
    with pytest.raises(InvalidTransition):
        may_set_decline_reason(current, reason_set=False)


def test_the_echo_of_a_confirmation_is_b4_and_of_a_decline_is_b5() -> None:
    assert echo_message(BookingStatus.CONFIRMED) is MessageId.B4
    assert echo_message(BookingStatus.DECLINED) is MessageId.B5


@pytest.mark.parametrize("status", [BookingStatus.REQUESTED, BookingStatus.EXPIRED])
def test_only_a_confirmation_or_a_decline_has_an_echo(status: BookingStatus) -> None:
    with pytest.raises(ValidationFailed):
        echo_message(status)


@pytest.mark.parametrize("role", [Role.REPORTER, Role.ANONYMOUS_LINK])
def test_a_reporter_or_a_link_for_the_same_service_may_answer(role: Role) -> None:
    assert responder_may_act(role, frozenset({SERVICE}), SERVICE) is True


@pytest.mark.parametrize("role", [Role.REPORTER, Role.ANONYMOUS_LINK])
def test_a_reporter_or_a_link_for_another_service_may_not_answer(role: Role) -> None:
    assert responder_may_act(role, frozenset({OTHER_SERVICE}), SERVICE) is False


@pytest.mark.parametrize("role", [Role.ADVISOR, Role.CLINICAL, Role.LEAD, Role.OWNER])
def test_a_staff_role_may_not_answer_for_the_service(role: Role) -> None:
    assert responder_may_act(role, frozenset({SERVICE}), SERVICE) is False


def test_a_requested_booking_is_cancelled_before_and_a_confirmed_one_after() -> None:
    assert cancel_target(BookingStatus.REQUESTED) is BookingStatus.CANCELLED_BEFORE
    assert cancel_target(BookingStatus.CONFIRMED) is BookingStatus.CANCELLED_AFTER


@pytest.mark.parametrize(
    "current",
    [BookingStatus.DECLINED, BookingStatus.EXPIRED, BookingStatus.CANCELLED_BEFORE],
)
def test_a_booking_in_any_other_state_cannot_be_cancelled(current: BookingStatus) -> None:
    with pytest.raises(InvalidTransition):
        cancel_target(current)


@pytest.mark.parametrize("role", [Role.ADVISOR, Role.CLINICAL])
def test_an_advisor_or_clinician_may_cancel(role: Role) -> None:
    assert advisor_may_cancel(role) is True


@pytest.mark.parametrize("role", [Role.REPORTER, Role.ANONYMOUS_LINK, Role.LEAD, Role.OWNER])
def test_no_other_role_may_cancel(role: Role) -> None:
    assert advisor_may_cancel(role) is False
