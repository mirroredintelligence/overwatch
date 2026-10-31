"""The visit offer and its states (DEC-1306 to DEC-1309): forward-only moves, and what each end
state erases. Values are synthetic."""

from datetime import UTC, datetime, timedelta

import pytest

from overwatch.domain.codes import Urgency
from overwatch.domain.errors import InvalidTransition, ValidationFailed
from overwatch.domain.model.visit import (
    END_STATES,
    PRACTITIONER_STATUSES,
    LocationChoice,
    VisitOffer,
    VisitState,
    default_settings,
    district_of_sector,
    transition,
)

NOW = datetime(2026, 10, 31, 10, 0, tzinfo=UTC)


def offer(state: VisitState = VisitState.OFFERED) -> VisitOffer:
    return VisitOffer(
        id="vo-1",
        booking_id="bk-1",
        reference="4821",
        service_id="svc-1",
        practitioner_id="p-1",
        need="Fall, no injury",
        sector="DT4 8",
        urgency=Urgency.WITHIN_2_HRS,
        offered_at=NOW,
        expires_at=NOW + timedelta(minutes=30),
        state=state,
        state_at=NOW,
        sealed_details="sealed",
        eta_at=NOW + timedelta(minutes=20),
    )


def test_an_offer_moves_forward_only() -> None:
    assert transition(VisitState.OFFERED, VisitState.ACCEPTED) is VisitState.ACCEPTED
    assert transition(VisitState.ACCEPTED, VisitState.ON_MY_WAY) is VisitState.ON_MY_WAY
    assert transition(VisitState.ON_MY_WAY, VisitState.ARRIVED) is VisitState.ARRIVED
    assert transition(VisitState.ARRIVED, VisitState.DONE) is VisitState.DONE
    for back in (VisitState.OFFERED, VisitState.ACCEPTED, VisitState.ON_MY_WAY):
        with pytest.raises(InvalidTransition):
            transition(VisitState.ARRIVED, back)


def test_an_estimate_can_be_refreshed_by_saying_on_my_way_again() -> None:
    assert transition(VisitState.ON_MY_WAY, VisitState.ON_MY_WAY) is VisitState.ON_MY_WAY
    with pytest.raises(InvalidTransition):
        transition(VisitState.ARRIVED, VisitState.ARRIVED)


@pytest.mark.parametrize("ended", sorted(END_STATES))
def test_nothing_leaves_an_end_state(ended: VisitState) -> None:
    for target in VisitState:
        with pytest.raises(InvalidTransition):
            transition(ended, target)


def test_an_offer_cannot_be_started_without_being_accepted() -> None:
    for status in PRACTITIONER_STATUSES:
        with pytest.raises(InvalidTransition):
            transition(VisitState.OFFERED, status)


def test_a_word_that_is_not_a_state_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        transition(VisitState.OFFERED, "accepted")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "ended",
    [
        VisitState.DONE,
        VisitState.NOT_REACHED,
    ],
)
def test_finishing_a_visit_erases_the_details_the_estimate_and_the_sector(
    ended: VisitState,
) -> None:
    moved = offer(VisitState.ARRIVED).with_state(ended, NOW)

    assert moved.sealed_details is None
    assert moved.eta_at is None
    assert moved.sector == "DT4"


@pytest.mark.parametrize("ended", [VisitState.DECLINED, VisitState.EXPIRED, VisitState.WITHDRAWN])
def test_an_offer_that_is_not_taken_up_keeps_nothing_of_the_visit(ended: VisitState) -> None:
    moved = offer().with_state(ended, NOW)

    assert (moved.sealed_details, moved.eta_at, moved.sector) == (None, None, "DT4")


def test_arriving_erases_the_estimate_but_keeps_the_details_for_the_visit() -> None:
    moved = offer(VisitState.ON_MY_WAY).with_state(VisitState.ARRIVED, NOW)

    assert moved.eta_at is None
    assert moved.sealed_details == "sealed"
    assert moved.sector == "DT4 8"


def test_a_naive_time_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        VisitOffer(
            id="vo-1",
            booking_id="bk-1",
            reference="4821",
            service_id="svc-1",
            practitioner_id="p-1",
            need="Fall, no injury",
            sector="DT4 8",
            urgency=Urgency.TODAY,
            offered_at=datetime(2026, 10, 31, 10, 0),
            expires_at=NOW,
            state=VisitState.OFFERED,
            state_at=NOW,
        )


def test_the_district_of_a_sector() -> None:
    assert district_of_sector("DT4 8") == "DT4"
    assert district_of_sector("DT4") == "DT4"


def test_settings_start_with_no_status_and_the_location_not_shared() -> None:
    settings = default_settings("p-1")

    assert (settings.status, settings.status_at) == (None, None)
    assert settings.location is LocationChoice.NEVER


@pytest.mark.parametrize(
    "under_way", [VisitState.ACCEPTED, VisitState.ON_MY_WAY, VisitState.ARRIVED]
)
def test_a_visit_under_way_can_be_withdrawn_and_loses_what_it_held(under_way: VisitState) -> None:
    moved = offer(under_way).with_state(VisitState.WITHDRAWN, NOW)

    assert (moved.state, moved.sealed_details, moved.eta_at, moved.sector) == (
        VisitState.WITHDRAWN,
        None,
        None,
        "DT4",
    )
