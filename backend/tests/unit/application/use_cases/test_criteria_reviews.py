"""The daily criteria review job (U31): the schedule rule, which needs no database.

The reminder, flag and schedule behaviour against Neo4j is in
tests/integration/application/test_criteria_reviews.py. Clock change: Sunday 25 October 2026 (BST
ends at 02:00 BST, so 07:00 London that day is GMT). Sample values only.
"""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from diucs.application.use_cases.criteria_reviews import REVIEW_RUN_AT, next_run_due

LONDON = ZoneInfo("Europe/London")


def _london(year: int, month: int, day: int, hour: int) -> datetime:
    return datetime(year, month, day, hour, tzinfo=LONDON).astimezone(UTC)


def test_the_job_runs_at_seven_in_the_morning_london_time() -> None:
    assert REVIEW_RUN_AT is not None
    assert (REVIEW_RUN_AT.hour, REVIEW_RUN_AT.minute) == (7, 0)


def test_a_run_on_the_friday_before_the_clock_change_schedules_saturday_at_0600z() -> None:
    # 23 October is still BST: 07:00 London is 06:00Z, and the next run is 24 October 06:00Z.
    assert next_run_due(_london(2026, 10, 23, 7)) == datetime(2026, 10, 24, 6, 0, tzinfo=UTC)


def test_a_run_on_the_day_before_the_clock_change_schedules_0700z_on_the_change_day() -> None:
    # 25 October is GMT: 07:00 London is 07:00Z.
    assert next_run_due(_london(2026, 10, 24, 7)) == datetime(2026, 10, 25, 7, 0, tzinfo=UTC)


def test_a_run_after_the_scheduled_hour_still_schedules_the_next_day() -> None:
    late = datetime(2026, 10, 24, 9, 30, tzinfo=UTC)
    assert next_run_due(late) == datetime(2026, 10, 25, 7, 0, tzinfo=UTC)


def test_the_next_run_is_always_an_instant_in_utc() -> None:
    due = next_run_due(_london(2026, 11, 2, 7))
    assert due.tzinfo is not None and due.utcoffset().total_seconds() == 0
