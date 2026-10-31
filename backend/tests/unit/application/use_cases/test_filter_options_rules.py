"""Pure rules of FilterOptions (U12): the not-suitable reasons, the warnings and the fit wording.

The sample values are synthetic: the service names and the 4 hrs 10 min data age come from the
"Advisor" artboard in docs/spec/ui-screens.md. No patient data appears here.
"""

from datetime import date, timedelta

import pytest

from diucs.application.ports.outbound.geo import LatLon, TravelRange
from diucs.application.use_cases.filter_options import (
    CRITERIA_NOT_REVIEWED_WARNING,
    LIMITED_WARNING,
    OLD_DATA_WARNING,
    OVER_CAPACITY_WARNING,
    Coverage,
    TravelLeg,
    coverage_of,
    criteria_warnings,
    data_age_warnings,
    fits_for,
    status_reason,
    status_warnings,
    travel_legs,
)
from diucs.domain.codes import CriteriaStatus, NeedCategory, Status
from diucs.domain.model.criteria import ServiceCriteria

TODAY = date(2026, 10, 29)


def _criteria(review_by: date) -> ServiceCriteria:
    return ServiceCriteria(
        id="crit-ucr-west-v3",
        service_id="svc-ucr-west",
        version=3,
        status=CriteriaStatus.CURRENT,
        age_min=18,
        age_max=None,
        districts=frozenset({"DT1", "DT2", "DT3", "DT4"}),
        accepts=frozenset({NeedCategory.FALL_NO_INJURY, NeedCategory.FRAILTY}),
        excludes=frozenset(),
        review_by=review_by,
        owner_role_id="role-lead-west",
    )


@pytest.mark.parametrize(
    ("status", "age", "reason"),
    [
        (Status.NOT_ACCEPTING, None, "not accepting"),
        (Status.NOT_ACCEPTING, timedelta(minutes=5), "not accepting"),
        (Status.OUT_OF_HOURS, None, "out of hours"),
        (
            Status.NOT_UPDATED,
            timedelta(hours=4, minutes=10),
            "not updated for 4 hrs 10 min. Phone to confirm.",
        ),
        (Status.NOT_UPDATED, None, "not updated. Phone to confirm."),
    ],
)
def test_a_status_that_may_not_take_a_case_gives_its_reason(
    status: Status, age: timedelta | None, reason: str
) -> None:
    assert status_reason(status, age) == reason


@pytest.mark.parametrize("status", [Status.ACCEPTING, Status.LIMITED, Status.OVER_CAPACITY])
def test_a_status_that_may_take_a_case_gives_no_reason_not_to(status: Status) -> None:
    assert status_reason(status, timedelta(minutes=9)) is None


def test_limited_and_over_capacity_stay_options_with_their_warning() -> None:
    assert status_warnings(Status.LIMITED) == (LIMITED_WARNING,)
    assert status_warnings(Status.OVER_CAPACITY) == (OVER_CAPACITY_WARNING,)
    assert status_warnings(Status.ACCEPTING) == ()


def test_data_over_two_hours_old_is_warned_and_two_hours_exactly_is_not() -> None:
    assert data_age_warnings(timedelta(hours=2)) == ()
    assert data_age_warnings(timedelta(hours=2, seconds=1)) == (OLD_DATA_WARNING,)
    assert data_age_warnings(timedelta(minutes=9)) == ()
    assert data_age_warnings(None) == ()


def test_a_review_date_that_has_passed_is_warned() -> None:
    assert criteria_warnings(_criteria(date(2026, 10, 28)), TODAY) == (
        CRITERIA_NOT_REVIEWED_WARNING,
    )


def test_a_review_date_today_or_later_is_not_warned() -> None:
    assert criteria_warnings(_criteria(TODAY), TODAY) == ()
    assert criteria_warnings(_criteria(date(2026, 11, 30)), TODAY) == ()


def test_the_fit_names_the_postcode_and_the_needs_the_service_takes() -> None:
    criteria = _criteria(date(2026, 11, 30))

    assert fits_for(criteria, (NeedCategory.FALL_NO_INJURY, NeedCategory.FRAILTY)) == (
        "Covers this postcode",
        "Takes fall, frailty",
    )


def test_a_case_with_no_need_still_fits_on_the_postcode() -> None:
    assert fits_for(_criteria(date(2026, 11, 30)), ()) == ("Covers this postcode",)


# KI-626, KI-627, KI-801: the travel leg and the coverage circle.


def test_a_routed_range_is_one_leg_by_road_with_the_traffic_note_and_the_engines_source() -> None:
    legs = travel_legs("Ward B", TravelRange(35, 50, "Routing data, updated 2026-10-01"))

    assert legs == (
        TravelLeg(
            label="Patient to Ward B, by road",
            low_minutes=35,
            high_minutes=50,
            how="Typical weekday afternoon. The spread is from traffic.",
            source="Routing data, updated 2026-10-01",
        ),
    )


def test_a_straight_line_estimate_is_never_called_a_road_route() -> None:
    (leg,) = travel_legs("Ward B", TravelRange(30, 55, "straight-line estimate"))

    assert "road" not in leg.label
    assert "by road" not in leg.how
    assert leg.label == "Patient to Ward B, in a straight line"
    assert leg.source == "straight-line estimate"


def test_no_range_gives_no_leg() -> None:
    assert travel_legs("Ward B", None) == ()


def test_the_coverage_of_a_visiting_service_is_the_circle_of_the_districts_it_covers() -> None:
    places = {"DT1": LatLon(50.0, -2.0), "DT2": LatLon(50.2, -2.0)}

    found = coverage_of(["DT1", "DT2"], places.get)

    assert found is not None
    assert found.radius_km >= 11
    assert round(found.lat, 3) == 50.1


def test_a_district_the_locator_cannot_place_is_left_out_and_none_placed_gives_no_coverage() -> (
    None
):
    places = {"DT1": LatLon(50.0, -2.0)}

    assert coverage_of(["DT1", "ZZ9"], places.get) == Coverage(lat=50.0, lon=-2.0, radius_km=1)
    assert coverage_of(["ZZ9"], places.get) is None
    assert coverage_of([], places.get) is None


def test_a_snapshot_row_keeps_the_name_the_advisor_saw() -> None:
    from datetime import datetime, timedelta

    from diucs.application.use_cases.filter_options import _snapshot_row
    from diucs.application.use_cases.query_board import BoardEntry
    from diucs.domain.codes import ServiceCategory

    entry = BoardEntry(
        service_id="svc-1",
        name="UCR West",
        category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
        status=Status.OVER_CAPACITY,
        effective_available=0,
        over_by=2,
        used=14,
        established=12,
        pending=0,
        unit_label="patients",
        comment="",
        reported_at=datetime(2026, 10, 29, 9, 0),
        next_due_at=None,
        was_due_at=None,
    )

    row = _snapshot_row(entry, 14, timedelta(minutes=9), None, "option")

    assert row["name"] == "UCR West"
    assert row["over_by"] == 2


def test_a_snapshot_row_keeps_the_shown_position_and_a_service_not_suitable_has_none() -> None:
    from datetime import datetime, timedelta

    from diucs.application.use_cases.filter_options import _snapshot_row
    from diucs.application.use_cases.query_board import BoardEntry
    from diucs.domain.codes import ServiceCategory

    entry = BoardEntry(
        service_id="svc-1",
        name="UCR West",
        category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
        status=Status.ACCEPTING,
        effective_available=4,
        over_by=None,
        used=4,
        established=8,
        pending=0,
        unit_label="referrals",
        comment="",
        reported_at=datetime(2026, 10, 29, 9, 0),
        next_due_at=None,
        was_due_at=None,
    )

    shown = _snapshot_row(entry, 4, timedelta(minutes=9), None, "option", order=2)
    refused = _snapshot_row(entry, 4, timedelta(minutes=9), None, "not-suitable", "not accepting")

    assert shown["order"] == 2
    assert "order" not in refused
