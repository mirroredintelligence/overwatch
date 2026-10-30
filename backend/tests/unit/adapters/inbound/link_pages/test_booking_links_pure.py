"""The pure rules of the booking links (L02): the actions a request or a change link takes, the
state a closed booking shows, and the page body of a booking request. No Neo4j, no app.

Sample values only: booking 4821, UCR West, case-1001. No patient data.
"""

import json
from datetime import UTC, datetime, timedelta

import pytest

from diucs.application.use_cases.link_access import LinkAction
from diucs.adapters.inbound.link_pages.booking_links import (
    CHANGE_PURPOSE,
    CHANGE_TOKEN_LIFETIME,
    REQUEST_PURPOSE,
    check_change_action,
    check_request_action,
    gone_state,
    view_body,
)
from diucs.domain.codes import (
    AgeBand,
    BookingStatus,
    DeclineReason,
    NeedCategory,
    NotReachedReason,
    ReferrerType,
    Urgency,
    WithdrawReason,
)
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.booking import Booking
from diucs.domain.model.case import Case


def _at(hour: int, minute: int) -> datetime:
    return datetime(2026, 10, 29, hour, minute, tzinfo=UTC)


def _booking(status: BookingStatus = BookingStatus.REQUESTED) -> Booking:
    return Booking(
        id="bk-4821",
        reference="4821",
        service_id="ucr-west",
        case_id="case-1001",
        requester_id="advisor-1",
        status=status,
        requested_at=_at(14, 16),
        reply_by=_at(14, 26),
    )


def _case() -> Case:
    return Case(
        id="case-1001",
        reference="1001",
        referrer_type=ReferrerType.GP,
        age_band=AgeBand.A80_PLUS,
        postcode="DT4",
        needs=(NeedCategory.FALL_NO_INJURY, NeedCategory.FRAILTY),
        urgency=Urgency.WITHIN_2_HRS,
        scores=(),
        opened_at=_at(14, 0),
    )


def test_the_purposes_and_the_change_lifetime_are_the_prompt_values() -> None:
    assert REQUEST_PURPOSE == "booking-request"
    assert CHANGE_PURPOSE == "booking-change"
    assert CHANGE_TOKEN_LIFETIME == timedelta(hours=24)


def test_confirm_takes_no_reason_and_decline_takes_a_decline_reason() -> None:
    assert check_request_action(LinkAction(action="confirm")) is None
    assert check_request_action(LinkAction(action="decline")) is None
    assert check_request_action(
        LinkAction(action="decline", reason="outside-criteria")
    ) is DeclineReason.OUTSIDE_CRITERIA


@pytest.mark.parametrize(
    "action",
    [
        LinkAction(action="confirm", reason="full"),
        LinkAction(action="decline", reason="now-full"),
        LinkAction(action="number", value=4),
        LinkAction(action="closed"),
        LinkAction(action="withdraw", reason="staffing"),
    ],
)
def test_a_request_link_refuses_any_other_action_or_reason(action: LinkAction) -> None:
    with pytest.raises(ValidationFailed):
        check_request_action(action)


def test_withdraw_and_not_reached_take_their_own_reasons_only() -> None:
    assert check_change_action(LinkAction(action="withdraw", reason="staffing")) is (
        WithdrawReason.STAFFING
    )
    assert check_change_action(LinkAction(action="not-reached", reason="no-answer")) is (
        NotReachedReason.NO_ANSWER
    )


@pytest.mark.parametrize(
    "action",
    [
        LinkAction(action="withdraw"),
        LinkAction(action="withdraw", reason="no-answer"),
        LinkAction(action="not-reached", reason="staffing"),
        LinkAction(action="not-reached"),
        LinkAction(action="confirm"),
    ],
)
def test_a_change_link_refuses_a_missing_or_foreign_reason(action: LinkAction) -> None:
    with pytest.raises(ValidationFailed):
        check_change_action(action)


@pytest.mark.parametrize(
    ("status", "state"),
    [
        (BookingStatus.EXPIRED, "expired"),
        (BookingStatus.CANCELLED_BEFORE, "cancelled"),
        (BookingStatus.CANCELLED_AFTER, "cancelled"),
        (BookingStatus.DECLINED, "declined"),
        (BookingStatus.WITHDRAWN, "withdrawn"),
        (BookingStatus.NOT_REACHED, "not-reached"),
    ],
)
def test_a_closed_booking_shows_its_state_word(status: BookingStatus, state: str) -> None:
    assert gone_state(status) == state


def test_the_request_page_names_the_booking_and_no_postcode_name_or_case() -> None:
    body = view_body(_booking(), "UCR West", _case())
    assert set(body) == {
        "reference",
        "serviceName",
        "ageBand",
        "need",
        "urgency",
        "replyBy",
        "bookingStatus",
    }
    assert body["reference"] == "4821"
    assert body["serviceName"] == "UCR West"
    assert body["ageBand"] == "80+"
    assert body["need"] == "fall-no-injury and frailty"
    assert body["urgency"] == "within 2 hrs"
    assert "14:26" in body["replyBy"]
    assert body["bookingStatus"] == "requested"
    text = json.dumps(body)
    assert "DT4" not in text
    assert "case-1001" not in text
