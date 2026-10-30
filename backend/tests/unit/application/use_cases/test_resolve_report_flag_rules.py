"""The pure rules of report flag resolution and the flag descriptions (U39). No Neo4j."""

from datetime import UTC, datetime, timedelta

import pytest

from diucs.application.actor import Actor
from diucs.application.use_cases.resolve_report_flag import (
    check_lead,
    check_resolution,
    describe_flag,
    resolved_status,
    sequence_of,
)
from diucs.domain.codes import (
    Measure,
    ReportFlagReason,
    ReportSource,
    ReportType,
    Role,
)
from diucs.domain.errors import NotAllowed, ValidationFailed
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.flags import REPORT_FLAG_ACCEPTED, REPORT_FLAG_CHECKED, ReportFlag
from tests.support.actors import ACTOR_TENANT


def _actor(role: Role) -> Actor:
    return Actor(
        role=role,
        practitioner_id="prac-1",
        device_id=None,
        channel="web",
        service_ids=frozenset(),
        tenant_id=ACTOR_TENANT,
    )


def _report(
    number: str,
    value: int,
    at: datetime,
    source: ReportSource = ReportSource.TEXT,
    report_type: ReportType = ReportType.NUMBER,
) -> CapacityReport:
    confirmed = report_type is ReportType.CONFIRMED
    return CapacityReport(
        id=f"obs-{number}",
        service_id="ucr-east",
        value=value,
        measure=Measure.REFERRALS_ACCEPTABLE,
        effective_at=at,
        source=source,
        report_type=report_type,
        derived_from="obs-0" if confirmed else None,
    )


def _flag(reason: ReportFlagReason, report_id: str, at: datetime) -> ReportFlag:
    return ReportFlag(
        id="flag-1",
        report_id=report_id,
        service_id="ucr-east",
        reason=reason,
        status="open",
        created_at=at,
    )


# --- who may resolve -------------------------------------------------------------------------


def test_the_lead_may_resolve_a_flag() -> None:
    check_lead(_actor(Role.LEAD))


@pytest.mark.parametrize(
    "role", [Role.ADVISOR, Role.CLINICAL, Role.REPORTER, Role.EXEC, Role.OWNER]
)
def test_no_other_role_may_resolve_a_flag(role: Role) -> None:
    with pytest.raises(NotAllowed):
        check_lead(_actor(role))


# --- outcomes ----------------------------------------------------------------------------------


def test_checked_and_phoned_are_recorded_as_checked_and_accepted_is_accepted() -> None:
    assert resolved_status("checked") == REPORT_FLAG_CHECKED
    assert resolved_status("phoned") == REPORT_FLAG_CHECKED
    assert resolved_status("accepted") == REPORT_FLAG_ACCEPTED


@pytest.mark.parametrize("outcome", ["open", "suspended", "", "CHECKED", "resolved"])
def test_an_unknown_outcome_is_refused(outcome: str) -> None:
    with pytest.raises(ValidationFailed):
        resolved_status(outcome)
    with pytest.raises(ValidationFailed):
        check_resolution(outcome, None)


def test_phoned_needs_the_figure_the_lead_was_told() -> None:
    with pytest.raises(ValidationFailed):
        check_resolution("phoned", None)


@pytest.mark.parametrize("value", [0, 3, 999])
def test_phoned_accepts_zero_to_999(value: int) -> None:
    check_resolution("phoned", value)


@pytest.mark.parametrize("value", [-1, 1000, True])
def test_phoned_refuses_a_figure_outside_zero_to_999_or_a_boolean(value: object) -> None:
    with pytest.raises(ValidationFailed):
        check_resolution("phoned", value)  # type: ignore[arg-type]


@pytest.mark.parametrize("outcome", ["checked", "accepted"])
def test_a_figure_is_refused_unless_the_outcome_is_phoned(outcome: str) -> None:
    with pytest.raises(ValidationFailed):
        check_resolution(outcome, 3)


# --- descriptions -----------------------------------------------------------------------------

T1410 = datetime(2026, 10, 23, 13, 10, tzinfo=UTC)  # 14:10 London, BST
T1412 = datetime(2026, 10, 23, 13, 12, tzinfo=UTC)  # 14:12 London


def test_the_out_of_range_description_matches_the_example_exactly() -> None:
    first = _report("a", 40, T1410)
    second = _report("b", 40, T1412)
    flag = _flag(ReportFlagReason.OUT_OF_RANGE_TWICE, second.id, T1412)
    text = describe_flag(
        flag,
        service_name="UCR East",
        usual_range=(0, 8),
        report=second,
        window=[first, second],
    )
    assert text == (
        "UCR East reported 40, twice. Usual range 0 to 8. Sent 14:10 and 14:12 by text."
    )


def test_out_of_range_twice_with_two_different_figures_says_then() -> None:
    first = _report("a", 40, T1410)
    second = _report("b", 22, T1412)
    flag = _flag(ReportFlagReason.OUT_OF_RANGE_TWICE, second.id, T1412)
    text = describe_flag(
        flag, service_name="UCR East", usual_range=(0, 8), report=second, window=[first, second]
    )
    assert (
        text == "UCR East reported 40, then 22. Usual range 0 to 8. Sent 14:10 and 14:12 by text."
    )


def test_out_of_range_names_both_sources_when_they_differ() -> None:
    first = _report("a", 40, T1410, source=ReportSource.TEXT)
    second = _report("b", 40, T1412, source=ReportSource.APP)
    flag = _flag(ReportFlagReason.OUT_OF_RANGE_TWICE, second.id, T1412)
    text = describe_flag(
        flag, service_name="UCR East", usual_range=(0, 8), report=second, window=[first, second]
    )
    assert text.endswith("Sent 14:10 and 14:12 by text and app.")


def test_sequence_of_a_run_of_confirmations_then_numbers_reads_all_y_then_numbers() -> None:
    reports = [
        _report("1", 1, T1410, report_type=ReportType.CONFIRMED),
        _report("2", 9, T1410 + timedelta(minutes=1)),
        _report("3", 2, T1410 + timedelta(minutes=2)),
    ]
    assert sequence_of(reports) == "All Y, then 9, then 2"


def test_sequence_of_only_confirmations_is_all_y() -> None:
    reports = [
        _report("1", 1, T1410, report_type=ReportType.CONFIRMED),
        _report("2", 1, T1410 + timedelta(minutes=1), report_type=ReportType.CONFIRMED),
    ]
    assert sequence_of(reports) == "All Y"


def test_sequence_of_numbers_only_is_the_numbers_in_order() -> None:
    reports = [_report("1", 4, T1410), _report("2", 0, T1410 + timedelta(minutes=1))]
    assert sequence_of(reports) == "4, then 0"


def test_many_changes_describes_the_reports_in_the_window_and_their_span() -> None:
    first = _report("1", 1, T1410, report_type=ReportType.CONFIRMED)
    second = _report("2", 9, T1410 + timedelta(minutes=2))
    third = _report("3", 2, T1410 + timedelta(minutes=4))
    flag = _flag(ReportFlagReason.MANY_CHANGES, third.id, third.effective_at)
    text = describe_flag(
        flag,
        service_name="Ward A",
        usual_range=(0, 8),
        report=third,
        window=[first, second, third],
    )
    assert text == "Ward A: 3 reports in 4 minutes. All Y, then 9, then 2."


def test_a_single_report_in_the_window_still_counts_as_one_minute_at_least() -> None:
    only = _report("1", 2, T1410)
    flag = _flag(ReportFlagReason.MANY_CHANGES, only.id, T1410)
    text = describe_flag(
        flag, service_name="Ward A", usual_range=(0, 8), report=only, window=[only]
    )
    assert text == "Ward A: 1 report in 1 minute. 2."


def test_differs_from_phoned_says_what_was_reported_and_what_was_phoned() -> None:
    phoned = _report("p", 3, T1410, source=ReportSource.ADVISOR_PHONED)
    reported = _report("r", 7, T1412)
    flag = _flag(ReportFlagReason.DIFFERS_FROM_PHONED, reported.id, T1412)
    text = describe_flag(
        flag,
        service_name="UCR East",
        usual_range=(0, 8),
        report=reported,
        window=[phoned, reported],
    )
    assert text == "UCR East reported 7 by text, but the advisor phoned 3 at 14:10."
