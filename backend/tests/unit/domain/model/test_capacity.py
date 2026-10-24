"""Tests for diucs.domain.model.capacity: the capacity report value object (D02).

Reports are immutable measurements. A correction is a new report, never an edit. The latest
report is the one with the greatest effective_at. Sample values only; no patient data.
"""

import dataclasses
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest

from diucs.domain.codes import Measure, ReportSource, ReportType
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.capacity import CapacityReport, latest_report

SERVICE_ID = "svc-ucr-west"
MORNING = datetime(2026, 10, 23, 7, 15, tzinfo=UTC)


def assert_field(field: str, build: Callable[[], object]) -> None:
    with pytest.raises(ValidationFailed) as info:
        build()
    assert info.value.field == field


def report(**overrides: Any) -> CapacityReport:
    fields: dict[str, Any] = {
        "id": "r1",
        "service_id": SERVICE_ID,
        "value": 3,
        "measure": Measure.REFERRALS_ACCEPTABLE,
        "effective_at": MORNING,
        "source": ReportSource.TEXT,
        "report_type": ReportType.NUMBER,
    }
    fields.update(overrides)
    return CapacityReport(**fields)


# --- A text report builds --------------------------------------------------------------------


def test_text_report_of_three_builds_and_is_not_closed() -> None:
    r = report()
    assert r.value == 3
    assert r.service_id == SERVICE_ID
    assert r.measure is Measure.REFERRALS_ACCEPTABLE
    assert r.effective_at == MORNING
    assert r.source is ReportSource.TEXT
    assert r.report_type is ReportType.NUMBER
    assert r.performer_role_id is None
    assert r.derived_from is None
    assert r.is_closed is False


# --- Closed means a report of zero, for every measure except occupied patients ---------------


def test_value_zero_is_closed() -> None:
    assert report(value=0).is_closed is True


def test_value_zero_for_occupied_patients_is_not_closed() -> None:
    # Zero occupied patients is a fact about the ward, not a closure.
    r = report(value=0, measure=Measure.OCCUPIED_PATIENTS)
    assert r.is_closed is False


# --- Validation ------------------------------------------------------------------------------


def test_negative_value_is_rejected_with_field_value() -> None:
    assert_field("value", lambda: report(value=-1))


def test_naive_effective_at_is_rejected_with_field_effective_at() -> None:
    assert_field("effective_at", lambda: report(effective_at=datetime(2026, 10, 23, 7, 15)))


def test_confirmed_report_without_derived_from_is_rejected() -> None:
    assert_field("derived_from", lambda: report(report_type=ReportType.CONFIRMED))


def test_confirmed_report_with_derived_from_builds() -> None:
    r = report(report_type=ReportType.CONFIRMED, derived_from="r1")
    assert r.report_type is ReportType.CONFIRMED
    assert r.derived_from == "r1"


def test_number_report_does_not_need_derived_from() -> None:
    assert report(report_type=ReportType.NUMBER).derived_from is None


# --- Reports are immutable -------------------------------------------------------------------


def test_report_is_frozen() -> None:
    r = report()
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.value = 5  # type: ignore[misc]


# --- latest_report ---------------------------------------------------------------------------


def test_latest_of_no_reports_is_none() -> None:
    assert latest_report([]) is None


def test_latest_is_the_greatest_effective_at_regardless_of_input_order() -> None:
    early = report(id="early", value=3, effective_at=datetime(2026, 10, 23, 7, 15, tzinfo=UTC))
    late = report(id="late", value=1, effective_at=datetime(2026, 10, 23, 9, 12, tzinfo=UTC))
    middle = report(id="middle", value=2, effective_at=datetime(2026, 10, 23, 8, 0, tzinfo=UTC))
    result = latest_report([early, late, middle])
    assert result is not None
    assert result.id == "late"


def test_exact_tie_on_effective_at_returns_the_one_that_comes_last_in_input() -> None:
    first = report(id="first", value=3)
    second = report(id="second", value=4)
    result = latest_report([first, second])
    assert result is not None
    assert result.id == "second"


def test_latest_accepts_any_iterable() -> None:
    reports = (report(id=f"r{i}", effective_at=datetime(2026, 10, 23, i, 0, tzinfo=UTC)) for i in range(3))
    result = latest_report(reports)
    assert result is not None
    assert result.id == "r2"
