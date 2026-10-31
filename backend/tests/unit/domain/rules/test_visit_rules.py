"""The rules of the visit offer (DEC-1306 to DEC-1309). Values are synthetic."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from overwatch.domain.codes import BookingStatus, Urgency
from overwatch.domain.errors import ValidationFailed
from overwatch.domain.model.visit import (
    ShiftStatus,
    VisitOffer,
    VisitSettings,
    VisitState,
    default_settings,
)
from overwatch.domain.rules.postcode import postcode_sector
from overwatch.domain.rules.visit_rules import (
    STATUS_LIFETIME,
    VISIT_LAPSE,
    check_details,
    check_eta_minutes,
    close_overdue,
    current_status,
    due_by,
    effective_state,
    order_of_round,
)

NOW = datetime(2026, 10, 31, 10, 0, tzinfo=UTC)


def offer(
    offer_id: str = "vo-1",
    state: VisitState = VisitState.OFFERED,
    urgency: Urgency = Urgency.WITHIN_2_HRS,
    offered_at: datetime = NOW,
) -> VisitOffer:
    return VisitOffer(
        id=offer_id,
        booking_id="bk-1",
        reference="4821",
        service_id="svc-1",
        practitioner_id="p-1",
        need="Fall, no injury",
        sector="DT4 8",
        urgency=urgency,
        offered_at=offered_at,
        expires_at=offered_at + timedelta(minutes=30),
        state=state,
        state_at=offered_at,
    )


def test_an_open_offer_for_a_waiting_booking_is_offered() -> None:
    assert effective_state(offer(), BookingStatus.REQUESTED, NOW) is VisitState.OFFERED


def test_an_offer_past_its_time_reads_expired_with_no_timer() -> None:
    late = NOW + timedelta(minutes=30)

    assert effective_state(offer(), BookingStatus.REQUESTED, late) is VisitState.EXPIRED
    assert (
        effective_state(offer(), BookingStatus.REQUESTED, late - timedelta(seconds=1))
        is VisitState.OFFERED
    )


@pytest.mark.parametrize(
    "booking",
    [
        None,
        BookingStatus.CONFIRMED,
        BookingStatus.DECLINED,
        BookingStatus.EXPIRED,
        BookingStatus.CANCELLED_BEFORE,
    ],
)
def test_an_offer_whose_booking_is_no_longer_waiting_reads_withdrawn(
    booking: BookingStatus | None,
) -> None:
    assert effective_state(offer(), booking, NOW) is VisitState.WITHDRAWN


def test_a_visit_under_way_is_withdrawn_only_when_the_booking_is_cancelled_after_confirming() -> (
    None
):
    under_way = offer(state=VisitState.ON_MY_WAY)

    assert effective_state(under_way, BookingStatus.CONFIRMED, NOW) is VisitState.ON_MY_WAY
    assert effective_state(under_way, BookingStatus.NOT_REACHED, NOW) is VisitState.ON_MY_WAY
    assert effective_state(under_way, BookingStatus.CANCELLED_AFTER, NOW) is VisitState.WITHDRAWN


def test_an_end_state_is_never_rewritten() -> None:
    done = offer(state=VisitState.DONE)

    assert effective_state(done, BookingStatus.CANCELLED_AFTER, NOW) is VisitState.DONE


def test_two_hours_is_given_for_within_2_hrs_and_nothing_for_the_others() -> None:
    assert due_by(Urgency.WITHIN_2_HRS, NOW) == NOW + timedelta(hours=2)
    assert due_by(Urgency.TODAY, NOW) is None
    assert due_by(Urgency.PLANNED, NOW) is None


def test_the_round_is_ordered_by_when_visits_are_wanted_and_by_nothing_else() -> None:
    later = offer("a", urgency=Urgency.WITHIN_2_HRS, offered_at=NOW + timedelta(hours=1))
    sooner = offer("b", urgency=Urgency.WITHIN_2_HRS, offered_at=NOW)
    today = offer("c", urgency=Urgency.TODAY, offered_at=NOW - timedelta(hours=3))
    planned = offer("d", urgency=Urgency.PLANNED, offered_at=NOW - timedelta(hours=4))

    ordered = order_of_round([planned, today, later, sooner])

    assert [item.id for item in ordered] == ["b", "a", "d", "c"]
    assert order_of_round([]) == []


def test_the_order_ties_break_by_id_so_it_is_the_same_every_time() -> None:
    first, second = offer("x"), offer("y")

    assert [o.id for o in order_of_round([second, first])] == ["x", "y"]


def test_details_are_trimmed_and_checked_without_repeating_them() -> None:
    assert check_details("  1  High Street ", " Daughter, 07000 000000 ") == (
        "1 High Street",
        "Daughter, 07000 000000",
    )
    for bad in ("", "   ", "x" * 201, None, 5, "line\x00break"):
        with pytest.raises(ValidationFailed) as caught:
            check_details(bad, "Daughter")
        if isinstance(bad, str) and len(bad.strip()) > 3:
            assert bad not in str(caught.value)
    with pytest.raises(ValidationFailed):
        check_details("1 High Street", "y" * 121)


@pytest.mark.parametrize("value", [0, 241, -5, 1.5, True, "10", None])
def test_an_estimate_must_be_a_whole_number_of_minutes_from_1_to_240(value: object) -> None:
    with pytest.raises(ValidationFailed):
        check_eta_minutes(value)


def test_an_estimate_in_range_is_kept() -> None:
    assert (check_eta_minutes(1), check_eta_minutes(240)) == (1, 240)


def test_a_status_stands_for_twelve_hours() -> None:
    settings = VisitSettings("p-1", ShiftStatus.BREAK, NOW, default_settings("p-1").location)

    assert (
        current_status(settings, NOW + STATUS_LIFETIME - timedelta(seconds=1)) is ShiftStatus.BREAK
    )
    assert current_status(settings, NOW + STATUS_LIFETIME) is None
    assert current_status(replace(settings, status=None, status_at=None), NOW) is None


def test_a_sector_is_the_outward_code_and_the_first_inward_digit() -> None:
    assert postcode_sector("DT4 8AB") == "DT4 8"
    assert postcode_sector("BH21 3XY") == "BH21 3"
    assert postcode_sector("W1A 1AA") == "W1A 1"
    for bad in ("DT48AB", "DT4", "dt4 8ab", ""):
        with pytest.raises(ValidationFailed) as caught:
            postcode_sector(bad)
        assert bad not in str(caught.value) or bad == ""


def test_a_close_expires_an_offer_whose_time_is_up_and_withdraws_one_whose_booking_moved() -> None:
    late = NOW + timedelta(minutes=30)

    assert close_overdue(offer(), BookingStatus.REQUESTED, late) is VisitState.EXPIRED
    assert close_overdue(offer(), BookingStatus.CONFIRMED, late) is VisitState.EXPIRED
    assert close_overdue(offer(), BookingStatus.CONFIRMED, NOW) is VisitState.WITHDRAWN
    assert close_overdue(offer(), None, NOW) is VisitState.WITHDRAWN
    assert close_overdue(offer(), BookingStatus.REQUESTED, NOW) is None


def test_a_close_withdraws_a_visit_cancelled_or_not_finished_in_a_day() -> None:
    under_way = offer(state=VisitState.ON_MY_WAY)

    assert close_overdue(under_way, BookingStatus.CONFIRMED, NOW) is None
    assert close_overdue(under_way, BookingStatus.CANCELLED_AFTER, NOW) is VisitState.WITHDRAWN
    almost = NOW + VISIT_LAPSE - timedelta(seconds=1)
    assert close_overdue(under_way, BookingStatus.CONFIRMED, almost) is None
    assert (
        close_overdue(under_way, BookingStatus.CONFIRMED, NOW + VISIT_LAPSE) is VisitState.WITHDRAWN
    )


def test_a_close_leaves_a_visit_that_ended() -> None:
    for ended in (VisitState.DONE, VisitState.DECLINED, VisitState.WITHDRAWN):
        done = offer(state=ended)
        assert close_overdue(done, BookingStatus.CANCELLED_AFTER, NOW + VISIT_LAPSE) is None
