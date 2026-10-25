"""Effective available and pending counts (D06).

Rules: docs/spec/domain-rules.md section 1.6. Names: docs/spec/contracts.md, rules/availability.py.
A booking confirmed at exactly effective_at counts as after the report. Sample values only.
"""

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from diucs.domain.codes import BookingStatus, Measure, ReportSource, ReportType
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.rules.availability import effective_available, effective_occupied, pending_count

REPORTED_AT = datetime(2026, 10, 25, 13, 3, tzinfo=UTC)
NON_OCCUPIED_MEASURES = [m for m in Measure if m is not Measure.OCCUPIED_PATIENTS]


def ucr_report(value: int = 4) -> CapacityReport:
    return CapacityReport(
        id="r-ucr-west-1",
        service_id="svc-ucr-west",
        value=value,
        measure=Measure.REFERRALS_ACCEPTABLE,
        effective_at=REPORTED_AT,
        source=ReportSource.TEXT,
        report_type=ReportType.NUMBER,
    )


def occupied_report(value: int) -> CapacityReport:
    return CapacityReport(
        id="r-hah-1",
        service_id="svc-hospital-at-home",
        value=value,
        measure=Measure.OCCUPIED_PATIENTS,
        effective_at=REPORTED_AT,
        source=ReportSource.LINK,
        report_type=ReportType.NUMBER,
    )


def at(hour: int, minute: int) -> datetime:
    return datetime(2026, 10, 25, hour, minute, tzinfo=UTC)


# effective_available: free-count measures (domain-rules 1.6)


def test_no_bookings_leaves_the_reported_figure() -> None:
    assert effective_available(ucr_report(4), []) == 4


def test_one_booking_confirmed_after_the_report_takes_one_place() -> None:
    # The board example: "Available drops to 3".
    assert effective_available(ucr_report(4), [at(13, 19)]) == 3


def test_booking_confirmed_before_the_report_is_already_in_it() -> None:
    assert effective_available(ucr_report(4), [at(12, 50)]) == 4


def test_booking_confirmed_at_exactly_the_report_time_counts_as_after() -> None:
    assert effective_available(ucr_report(4), [REPORTED_AT]) == 3


def test_never_goes_below_zero() -> None:
    confirmed = [at(13, 10), at(13, 20), at(13, 30)]
    assert effective_available(ucr_report(1), confirmed) == 0


def test_only_bookings_after_the_report_are_subtracted() -> None:
    confirmed = [at(12, 0), at(13, 3), at(13, 4), at(14, 0)]
    assert effective_available(ucr_report(10), confirmed) == 7


def test_accepts_any_sequence_of_confirmation_times() -> None:
    confirmed = (at(13, 19), at(13, 40))
    assert effective_available(ucr_report(4), confirmed) == 2


def test_available_refuses_the_occupied_patients_measure() -> None:
    report = CapacityReport(
        id="r-hah-2",
        service_id="svc-hospital-at-home",
        value=14,
        measure=Measure.OCCUPIED_PATIENTS,
        effective_at=REPORTED_AT,
        source=ReportSource.LINK,
        report_type=ReportType.NUMBER,
    )
    with pytest.raises(ValueError):
        effective_available(report, [at(13, 19)])


@given(
    value=st.integers(min_value=0, max_value=200),
    offsets_minutes=st.lists(st.integers(min_value=-600, max_value=600), max_size=30),
)
def test_available_is_never_negative_and_matches_the_count_after_the_report(
    value: int, offsets_minutes: list[int]
) -> None:
    confirmed = [REPORTED_AT + timedelta(minutes=m) for m in offsets_minutes]
    after = sum(1 for t in confirmed if t >= REPORTED_AT)
    result = effective_available(ucr_report(value), confirmed)
    assert result >= 0
    assert result == max(0, value - after)


@given(
    value=st.integers(min_value=0, max_value=200),
    offsets_minutes=st.lists(st.integers(min_value=-600, max_value=600), max_size=30),
)
def test_adding_a_confirmation_never_raises_the_available_figure(
    value: int, offsets_minutes: list[int]
) -> None:
    confirmed = [REPORTED_AT + timedelta(minutes=m) for m in offsets_minutes]
    report = ucr_report(value)
    before = effective_available(report, confirmed)
    after = effective_available(report, [*confirmed, REPORTED_AT + timedelta(minutes=1)])
    assert after <= before


# effective_occupied: occupied-patients measure


def test_occupied_adds_one_patient_for_a_confirmation_after_the_report() -> None:
    # Hospital at home: reported 14 occupied, one confirmed after, so 15 occupied.
    assert effective_occupied(occupied_report(14), [at(13, 19)]) == 15


def test_occupied_ignores_confirmations_before_the_report() -> None:
    assert effective_occupied(occupied_report(14), [at(12, 50)]) == 14


def test_occupied_counts_a_confirmation_at_exactly_the_report_time() -> None:
    assert effective_occupied(occupied_report(14), [REPORTED_AT]) == 15


def test_occupied_with_no_bookings_is_the_reported_count() -> None:
    assert effective_occupied(occupied_report(14), []) == 14


@pytest.mark.parametrize("measure", NON_OCCUPIED_MEASURES)
def test_occupied_refuses_every_free_count_measure(measure: Measure) -> None:
    report = CapacityReport(
        id="r-ucr-west-2",
        service_id="svc-ucr-west",
        value=4,
        measure=measure,
        effective_at=REPORTED_AT,
        source=ReportSource.TEXT,
        report_type=ReportType.NUMBER,
    )
    with pytest.raises(ValueError):
        effective_occupied(report, [at(13, 19)])


@given(
    value=st.integers(min_value=0, max_value=200),
    offsets_minutes=st.lists(st.integers(min_value=-600, max_value=600), max_size=30),
)
def test_occupied_is_the_report_plus_the_count_after_the_report(
    value: int, offsets_minutes: list[int]
) -> None:
    confirmed = [REPORTED_AT + timedelta(minutes=m) for m in offsets_minutes]
    after = sum(1 for t in confirmed if t >= REPORTED_AT)
    assert effective_occupied(occupied_report(value), confirmed) == value + after


# pending_count: bookings in requested state (domain-rules 1.6)


def test_pending_counts_only_requested_bookings() -> None:
    statuses = [
        BookingStatus.REQUESTED,
        BookingStatus.CONFIRMED,
        BookingStatus.REQUESTED,
        BookingStatus.DECLINED,
        BookingStatus.EXPIRED,
    ]
    assert pending_count(statuses) == 2


def test_pending_of_nothing_is_zero() -> None:
    assert pending_count([]) == 0


@pytest.mark.parametrize("status", list(BookingStatus))
def test_pending_counts_one_status_as_one_only_when_requested(status: BookingStatus) -> None:
    expected = 1 if status is BookingStatus.REQUESTED else 0
    assert pending_count([status]) == expected


def test_pending_accepts_a_one_pass_iterable() -> None:
    def statuses() -> Iterable[BookingStatus]:
        yield BookingStatus.REQUESTED
        yield BookingStatus.WITHDRAWN
        yield BookingStatus.REQUESTED

    assert pending_count(statuses()) == 2


class OtherCodes(StrEnum):
    """A different enum whose member has the same value as a booking status (lesson L3)."""

    REQUESTED = "requested"


def test_pending_does_not_count_a_member_of_another_enum_with_the_same_value() -> None:
    statuses: list[Any] = [OtherCodes.REQUESTED]
    assert pending_count(statuses) == 0


@given(st.lists(st.sampled_from(list(BookingStatus)), max_size=40))
def test_pending_equals_the_number_of_requested_statuses(statuses: list[BookingStatus]) -> None:
    assert pending_count(statuses) == sum(1 for s in statuses if s is BookingStatus.REQUESTED)
