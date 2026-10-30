"""The daily tenant invariant job (TEN-031): the schedule rule and the work kind, which need no
database. The job itself against Neo4j, its replay and its seeding are in
tests/integration/application/test_tenant_invariants.py.

Clock change: Sunday 25 October 2026 (BST ends at 02:00 BST, so 03:30 London that day is GMT).
"""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from diucs.application.use_cases.tenant_invariants import (
    INVARIANT_RUN_AT,
    first_run_due,
    invariant_work_id,
    next_run_due,
)
from diucs.application.work import WorkKind

LONDON = ZoneInfo("Europe/London")


def _london(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=LONDON).astimezone(UTC)


def test_the_job_is_a_work_kind_of_its_own() -> None:
    assert WorkKind.INVARIANT_CHECK.value == "invariant-check"


def test_the_job_runs_at_half_past_three_in_the_morning_london_time() -> None:
    assert (INVARIANT_RUN_AT.hour, INVARIANT_RUN_AT.minute) == (3, 30)


def test_a_run_on_the_friday_before_the_clock_change_schedules_saturday_at_0230z() -> None:
    # 23 October is still BST: 03:30 London is 02:30Z, and the next run is 24 October 02:30Z.
    assert next_run_due(_london(2026, 10, 23, 3, 30)) == datetime(2026, 10, 24, 2, 30, tzinfo=UTC)


def test_a_run_on_the_day_before_the_clock_change_schedules_0330z_on_the_change_day() -> None:
    assert next_run_due(_london(2026, 10, 24, 3, 30)) == datetime(2026, 10, 25, 3, 30, tzinfo=UTC)


def test_a_run_after_the_scheduled_hour_still_schedules_the_next_day() -> None:
    late = datetime(2026, 10, 24, 9, 30, tzinfo=UTC)
    assert next_run_due(late) == datetime(2026, 10, 25, 3, 30, tzinfo=UTC)


def test_the_first_run_is_today_when_the_hour_is_ahead_and_tomorrow_when_it_has_passed() -> None:
    early = datetime(2026, 10, 24, 1, 0, tzinfo=UTC)
    assert first_run_due(early) == datetime(2026, 10, 24, 2, 30, tzinfo=UTC)
    late = datetime(2026, 10, 24, 13, 0, tzinfo=UTC)
    assert first_run_due(late) == datetime(2026, 10, 25, 3, 30, tzinfo=UTC)


def test_the_next_run_is_always_an_instant_in_utc() -> None:
    due = next_run_due(_london(2026, 11, 2, 3, 30))
    assert due.tzinfo is not None and due.utcoffset().total_seconds() == 0


def test_the_work_id_is_derived_from_the_tenant_and_the_london_date_of_the_run() -> None:
    due = datetime(2026, 10, 25, 3, 30, tzinfo=UTC)
    assert invariant_work_id("tenant-a", due) == "invariant-check:tenant-a:2026-10-25"
    assert invariant_work_id("tenant-b", due) != invariant_work_id("tenant-a", due)
    assert invariant_work_id("tenant-a", due) != invariant_work_id(
        "tenant-a", datetime(2026, 10, 26, 3, 30, tzinfo=UTC)
    )
