"""Tests for diucs.domain.rules.status: the service status rule (D07).

Rules: docs/spec/domain-rules.md 1.2 and 1.3 (first match wins), and the D07 prompt. Sample
services are the ones in the spec's sample board. Friday 2026-10-23 is in British summer time
(14:12 BST at 13:12Z). The clocks go back on 2026-10-25, so Monday 2026-10-26 is on GMT.
Every instant is UTC (lesson L4). Limited uses integer arithmetic (no floats).
DEC-029 governs no-report-ever overdue. DEC-033 governs the figures for occupied patients.
"""

from dataclasses import replace
from datetime import UTC, datetime, time, timedelta, timezone
from typing import Final

import pytest
from hypothesis import given
from hypothesis import strategies as st

from diucs.domain.codes import (
    Cadence,
    Channel,
    Measure,
    ReportSource,
    ReportType,
    ServiceCategory,
    Status,
)
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.service import AvailableTime, ServiceProfile
from diucs.domain.rules.freshness import Freshness
from diucs.domain.rules.status import ServiceState, compute_status

BST: Final = timezone(timedelta(hours=1))
FRIDAY_NOW: Final = datetime(2026, 10, 23, 13, 12, tzinfo=UTC)
REPORT_AT: Final = datetime(2026, 10, 23, 13, 3, tzinfo=UTC)


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def base_profile(**changes: object) -> ServiceProfile:
    profile = ServiceProfile(
        id="svc-ucr-west",
        name="UCR West",
        category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
        measure=Measure.REFERRALS_ACCEPTABLE,
        unit_label="referrals in the next 2 hrs",
        established_capacity=8,
        can_exceed_established=False,
        usual_range=(0, 8),
        cadence=Cadence.EVERY_2_HRS,
        available_times=(AvailableTime.weekdays(time(8, 0), time(20, 0)),),
        channel=Channel.TEXT,
    )
    return replace(profile, **changes)  # type: ignore[arg-type]


UCR_WEST: Final = base_profile()


def report(
    value: int,
    *,
    at: datetime = REPORT_AT,
    measure: Measure = Measure.REFERRALS_ACCEPTABLE,
    service_id: str = "svc-ucr-west",
) -> CapacityReport:
    return CapacityReport(
        id="rep-1",
        service_id=service_id,
        value=value,
        measure=measure,
        effective_at=at,
        source=ReportSource.TEXT,
        report_type=ReportType.NUMBER,
    )


def state(
    profile: ServiceProfile,
    latest: CapacityReport | None,
    *,
    confirmed: tuple[datetime, ...] = (),
    now: datetime = FRIDAY_NOW,
) -> ServiceState:
    return compute_status(profile, latest, confirmed, now)


def test_ucr_west_with_four_free_is_accepting() -> None:
    # UCR West, established 8, reported 4 free at 13:03Z. Used 4 of 8 (50%) is below 80%.
    result = state(UCR_WEST, report(4))
    assert result == ServiceState(
        status=Status.ACCEPTING,
        effective_available=4,
        used=4,
        over_by=None,
        freshness=Freshness(
            overdue=False, age=timedelta(minutes=9), stale_warning=False, was_due=None
        ),
    )


def test_ucr_east_with_one_free_is_limited() -> None:
    # Established 8, one free: used 7 of 8 is 88%, at or above 80%.
    east = base_profile(id="svc-ucr-east", name="UCR East")
    result = state(east, report(1, service_id="svc-ucr-east"))
    assert (result.status, result.effective_available, result.used) == (Status.LIMITED, 1, 7)


def test_ward_a_with_two_beds_free_is_limited() -> None:
    # Established 12, two beds: used 10 of 12 is 83%.
    ward_a = base_profile(
        id="svc-ward-a",
        name="Community hospital · Ward A",
        category=ServiceCategory.INPATIENT_BEDS,
        measure=Measure.FREE_BEDS,
        established_capacity=12,
        usual_range=(0, 12),
    )
    result = state(ward_a, report(2, measure=Measure.FREE_BEDS, service_id="svc-ward-a"))
    assert (result.status, result.used) == (Status.LIMITED, 10)


def test_ward_b_with_five_beds_free_is_accepting() -> None:
    # Established 12, five beds: used 7 of 12 is 58%.
    ward_b = base_profile(
        id="svc-ward-b",
        name="Community hospital · Ward B",
        category=ServiceCategory.INPATIENT_BEDS,
        measure=Measure.FREE_BEDS,
        established_capacity=12,
        usual_range=(0, 12),
    )
    result = state(ward_b, report(5, measure=Measure.FREE_BEDS, service_id="svc-ward-b"))
    assert (result.status, result.used) == (Status.ACCEPTING, 7)


def test_reablement_with_three_packages_is_accepting() -> None:
    # Established 10, three packages: used 7 of 10 is 70%, below 80%.
    reablement = base_profile(
        id="svc-reablement",
        name="Reablement",
        category=ServiceCategory.REABLEMENT,
        measure=Measure.PACKAGES_FREE,
        established_capacity=10,
        usual_range=(0, 10),
    )
    result = state(
        reablement, report(3, measure=Measure.PACKAGES_FREE, service_id="svc-reablement")
    )
    assert (result.status, result.effective_available, result.used) == (Status.ACCEPTING, 3, 7)


def test_zero_reported_is_not_accepting() -> None:
    # SDEC Site 2 reports zero slots: it is closed to referrals.
    sdec = base_profile(
        id="svc-sdec-2",
        name="SDEC · Site 2",
        category=ServiceCategory.SAME_DAY_EMERGENCY_CARE,
        measure=Measure.FREE_SLOTS,
        established_capacity=8,
    )
    result = state(sdec, report(0, measure=Measure.FREE_SLOTS, service_id="svc-sdec-2"))
    assert (result.status, result.effective_available, result.used) == (Status.NOT_ACCEPTING, 0, 8)


HOSPITAL_AT_HOME: Final = base_profile(
    id="svc-hah",
    name="Hospital at home",
    category=ServiceCategory.HOSPITAL_AT_HOME_OR_VIRTUAL_WARD,
    measure=Measure.OCCUPIED_PATIENTS,
    established_capacity=12,
    can_exceed_established=True,
    usual_range=(0, 20),
)


def occupied(value: int) -> CapacityReport:
    return report(value, measure=Measure.OCCUPIED_PATIENTS, service_id="svc-hah")


def test_occupied_above_established_is_over_capacity_by_the_excess() -> None:
    # Hospital at home, established 12, can exceed, 14 occupied: over by 2.
    result = state(HOSPITAL_AT_HOME, occupied(14))
    assert result == ServiceState(
        status=Status.OVER_CAPACITY,
        effective_available=None,
        used=14,
        over_by=2,
        freshness=Freshness(
            overdue=False, age=timedelta(minutes=9), stale_warning=False, was_due=None
        ),
    )


@pytest.mark.parametrize(
    ("can_exceed", "expected"),
    [(False, Status.NOT_ACCEPTING), (True, Status.LIMITED)],
)
def test_occupied_exactly_at_established_depends_on_can_exceed(
    can_exceed: bool, expected: Status
) -> None:
    profile = replace(HOSPITAL_AT_HOME, can_exceed_established=can_exceed)
    result = state(profile, occupied(12))
    assert (result.status, result.used, result.over_by) == (expected, 12, None)


@pytest.mark.parametrize(
    ("occupied_now", "expected"),
    [(11, Status.LIMITED), (10, Status.LIMITED), (9, Status.ACCEPTING)],
)
def test_occupied_below_established_uses_the_limited_share(
    occupied_now: int, expected: Status
) -> None:
    # Established 12: 10 occupied is 83% (limited), 9 is 75% (accepting).
    profile = replace(HOSPITAL_AT_HOME, can_exceed_established=False)
    assert state(profile, occupied(occupied_now)).status is expected


def test_booking_confirmed_after_the_report_reduces_available() -> None:
    # Report 4 at 13:03Z. One booking confirmed at 13:19Z, now 13:25Z: available 3, used 5.
    result = state(
        UCR_WEST,
        report(4),
        confirmed=(utc(2026, 10, 23, 13, 19),),
        now=utc(2026, 10, 23, 13, 25),
    )
    assert (result.status, result.effective_available, result.used) == (Status.ACCEPTING, 3, 5)


def test_booking_confirmed_before_the_report_is_not_subtracted() -> None:
    result = state(UCR_WEST, report(4), confirmed=(utc(2026, 10, 23, 12, 0),))
    assert result.effective_available == 4


def test_bookings_beyond_the_report_floor_at_zero_and_close_the_service() -> None:
    # Two free and three confirmed since the report: available floors at 0. Used 8 of 8.
    result = state(
        UCR_WEST,
        report(2),
        confirmed=(utc(2026, 10, 23, 13, 4), utc(2026, 10, 23, 13, 5), utc(2026, 10, 23, 13, 6)),
    )
    assert (result.status, result.effective_available, result.used) == (Status.NOT_ACCEPTING, 0, 8)


def test_occupied_count_includes_bookings_confirmed_since_the_report() -> None:
    # Occupied 11 of 12, one booking confirmed since: 12 of 12, so not accepting (cannot exceed).
    result = state(
        replace(HOSPITAL_AT_HOME, can_exceed_established=False),
        occupied(11),
        confirmed=(utc(2026, 10, 23, 13, 10),),
    )
    assert (result.status, result.used) == (Status.NOT_ACCEPTING, 12)


@pytest.mark.parametrize(
    ("established", "available", "expected"),
    [(10, 2, Status.LIMITED), (10, 3, Status.ACCEPTING)],
)
def test_at_the_limit_is_limited_and_one_above_is_accepting(
    established: int, available: int, expected: Status
) -> None:
    # Established 10: 2 free is 8 used, exactly 80%; 3 free is 70%.
    profile = base_profile(established_capacity=established)
    assert state(profile, report(available)).status is expected


def test_suspended_service_is_not_updated_even_with_a_fresh_report() -> None:
    profile = base_profile(suspended=True)
    result = state(profile, report(4))
    assert (result.status, result.effective_available, result.used) == (Status.NOT_UPDATED, 4, 4)


def test_suspended_outside_hours_is_still_not_updated() -> None:
    # Rule 1 comes before rule 2: a suspended service never shows out-of-hours.
    profile = base_profile(suspended=True)
    result = state(profile, None, now=utc(2026, 10, 24, 12, 0))
    assert result.status is Status.NOT_UPDATED


def test_saturday_is_out_of_hours_even_with_no_report() -> None:
    # Saturday 2026-10-24 at 12:00Z (13:00 BST). Weekdays only.
    result = state(UCR_WEST, None, now=utc(2026, 10, 24, 12, 0))
    assert result == ServiceState(
        status=Status.OUT_OF_HOURS,
        effective_available=None,
        used=None,
        over_by=None,
        freshness=result.freshness,
    )


def test_out_of_hours_wins_over_no_report_ever_on_monday_morning() -> None:
    # Monday 2026-10-26 at 06:30Z (06:30 GMT). The service opens at 08:00. DEC-029 makes the
    # service overdue, but rule 2 comes first.
    result = state(UCR_WEST, None, now=utc(2026, 10, 26, 6, 30))
    assert result.status is Status.OUT_OF_HOURS
    assert result.freshness.overdue is True


def test_in_hours_with_no_report_once_first_reply_by_passed_is_not_updated() -> None:
    # The 08:00 BST due is 07:00Z, its reply-by 07:30Z. At 08:00Z the service is in hours.
    result = state(UCR_WEST, None, now=utc(2026, 10, 23, 8, 0))
    assert result == ServiceState(
        status=Status.NOT_UPDATED,
        effective_available=None,
        used=None,
        over_by=None,
        freshness=result.freshness,
    )
    assert result.freshness.overdue is True


def test_overdue_is_not_updated_but_the_last_figure_is_still_shown() -> None:
    # Last report 10:00Z with 4 free. The 11:00Z due passed its reply-by at 11:30Z.
    result = state(UCR_WEST, report(4, at=utc(2026, 10, 23, 10, 0)), now=utc(2026, 10, 23, 15, 40))
    assert result.status is Status.NOT_UPDATED
    assert (result.effective_available, result.used) == (4, 4)
    assert result.freshness.overdue is True


def test_free_report_above_established_has_no_negative_used() -> None:
    # A report of 10 on a service established at 8 is accepted as reported; used floors at 0.
    result = state(UCR_WEST, report(10))
    assert (result.status, result.effective_available, result.used) == (Status.ACCEPTING, 10, 0)


def test_wrong_service_report_is_refused() -> None:
    with pytest.raises(ValueError, match="service"):
        state(UCR_WEST, report(4, service_id="svc-other"))


def test_report_with_another_measure_is_refused() -> None:
    with pytest.raises(ValueError, match="measure"):
        state(UCR_WEST, report(4, measure=Measure.FREE_BEDS))


def test_naive_now_is_refused() -> None:
    with pytest.raises(ValueError):
        compute_status(UCR_WEST, report(4), (), datetime(2026, 10, 23, 13, 12))


@given(
    minutes_now=st.integers(min_value=0, max_value=14 * 24 * 60),
    minutes_since_report=st.integers(min_value=0, max_value=7 * 24 * 60),
    value=st.integers(min_value=0, max_value=8),
    has_report=st.booleans(),
)
def test_accepting_is_never_shown_for_an_overdue_or_missing_figure(
    minutes_now: int, minutes_since_report: int, value: int, has_report: bool
) -> None:
    now = utc(2026, 10, 19) + timedelta(minutes=minutes_now)
    latest = report(value, at=now - timedelta(minutes=minutes_since_report)) if has_report else None
    result = compute_status(UCR_WEST, latest, (), now)

    if latest is None or result.freshness.overdue:
        assert result.status in {Status.NOT_UPDATED, Status.OUT_OF_HOURS}
    if result.status is Status.ACCEPTING:
        assert latest is not None
        assert result.freshness.overdue is False
        assert result.used is not None and result.used >= 0
