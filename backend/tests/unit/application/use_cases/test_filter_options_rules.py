"""Pure rules of FilterOptions (U12): the not-suitable reasons, the warnings and the fit wording.

The sample values are synthetic: the service names and the 4 hrs 10 min data age come from the
"Advisor" artboard in docs/spec/ui-screens.md. No patient data appears here.
"""

from datetime import date, timedelta

import pytest

from diucs.application.use_cases.filter_options import (
    CRITERIA_NOT_REVIEWED_WARNING,
    LIMITED_WARNING,
    OLD_DATA_WARNING,
    OVER_CAPACITY_WARNING,
    criteria_warnings,
    data_age_warnings,
    fits_for,
    status_reason,
    status_warnings,
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
        "Takes fall, no injury and frailty",
    )


def test_a_case_with_no_need_still_fits_on_the_postcode() -> None:
    assert fits_for(_criteria(date(2026, 11, 30)), ()) == ("Covers this postcode",)
