"""The age test behind hazard H-31 (U05): a Y confirms a figure only while it is inside its window.

`figure_is_out_of_date(figure_as_of, prompt_sent_at)` is true when the figure the prompt named is
older than CONFIRMABLE_FIGURE_AGE at the moment the prompt was sent (DEC-148). Instants are
compared in UTC, never as London wall-clock times, so the 2026 clock changes cannot move the line
(lesson L4). Boundary: exactly the window is still inside it, as D05's `stale_warning` (strictly
more than 2 hours old).
"""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given
from hypothesis import strategies as st

from diucs.application.prompt_judgement import (
    CONFIRMABLE_FIGURE_AGE,
    figure_is_out_of_date,
    recorded_since_prompt,
)
from diucs.application.use_cases.handle_inbound_text import CONFIRM_PROCESSING_LIMIT
from diucs.domain.codes import Measure, ReportSource, ReportType
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.rules.freshness import STALE_WARNING_AFTER

LONDON = ZoneInfo("Europe/London")
ONE_SECOND = timedelta(seconds=1)

# A prompt sent at these instants, with the clock changes either side of them: an ordinary
# Friday, the spring change (01:00 GMT to 02:00 BST on 2026-03-29) and the autumn change
# (02:00 BST to 01:00 GMT on 2026-10-25).
SENT_ORDINARY = datetime(2026, 10, 23, 11, 0, tzinfo=UTC)  # 12:00 BST
SENT_AFTER_SPRING_CHANGE = datetime(2026, 3, 29, 2, 30, tzinfo=UTC)  # 03:30 BST
SENT_AFTER_AUTUMN_CHANGE = datetime(2026, 10, 25, 2, 30, tzinfo=UTC)  # 02:30 GMT


def test_the_window_is_the_stale_warning_of_the_board() -> None:
    assert CONFIRMABLE_FIGURE_AGE == STALE_WARNING_AFTER == timedelta(hours=2)


def test_the_processing_limit_is_ten_minutes() -> None:
    """[ASSUMED] in domain-rules.md: a Y waiting longer than this between receipt and processing is
    not recorded (DEC-148 item 19)."""
    assert timedelta(minutes=10) == CONFIRM_PROCESSING_LIMIT


@pytest.mark.parametrize(
    "sent_at", [SENT_ORDINARY, SENT_AFTER_SPRING_CHANGE, SENT_AFTER_AUTUMN_CHANGE]
)
@pytest.mark.parametrize(
    ("age", "out_of_date"),
    [
        (timedelta(0), False),
        (timedelta(hours=1, minutes=45), False),
        (CONFIRMABLE_FIGURE_AGE - ONE_SECOND, False),  # inside the window
        (CONFIRMABLE_FIGURE_AGE, False),  # at the window: still inside it
        (CONFIRMABLE_FIGURE_AGE + ONE_SECOND, True),  # after the window
        (timedelta(hours=26), True),  # the day before
        (timedelta(days=30), True),
    ],
)
def test_the_window_boundary_in_utc_on_ordinary_and_clock_change_days(
    sent_at: datetime, age: timedelta, out_of_date: bool
) -> None:
    assert figure_is_out_of_date(sent_at - age, sent_at) is out_of_date


@pytest.mark.parametrize(
    ("as_of", "sent_at", "out_of_date"),
    [
        # Autumn: 01:30 BST is 00:30Z and 02:30 GMT is 02:30Z, two hours apart but one hour apart
        # on the wall clock. Reading wall times would call this inside the window one second late.
        (
            datetime(2026, 10, 25, 1, 30, tzinfo=LONDON, fold=0),
            datetime(2026, 10, 25, 2, 30, tzinfo=LONDON),
            False,
        ),
        (
            datetime(2026, 10, 25, 1, 30, tzinfo=LONDON, fold=0),
            datetime(2026, 10, 25, 2, 30, 1, tzinfo=LONDON),
            True,
        ),
        # Spring: 00:30 GMT and 03:30 BST are two hours apart but three on the wall clock. Reading
        # wall times would call an exactly-at-the-window figure out of date.
        (
            datetime(2026, 3, 29, 0, 30, tzinfo=LONDON),
            datetime(2026, 3, 29, 3, 30, tzinfo=LONDON),
            False,
        ),
        (
            datetime(2026, 3, 29, 0, 30, tzinfo=LONDON),
            datetime(2026, 3, 29, 3, 30, 1, tzinfo=LONDON),
            True,
        ),
        # The second 01:30 of the autumn fold is an hour after the first.
        (
            datetime(2026, 10, 25, 1, 30, tzinfo=LONDON, fold=1),
            datetime(2026, 10, 25, 3, 30, 1, tzinfo=LONDON),
            True,
        ),
        (
            datetime(2026, 10, 25, 1, 30, tzinfo=LONDON, fold=1),
            datetime(2026, 10, 25, 3, 30, tzinfo=LONDON),
            False,
        ),
    ],
)
def test_london_wall_times_are_compared_as_instants(
    as_of: datetime, sent_at: datetime, out_of_date: bool
) -> None:
    assert figure_is_out_of_date(as_of, sent_at) is out_of_date


def test_a_figure_newer_than_the_prompt_is_not_out_of_date() -> None:
    """Age only: the figure is not too old. A Y is still refused for it, because a number reported
    after the prompt is a figure the reporter was never shown (H-32, tested in the integration
    file), which is a separate test from this one."""
    assert figure_is_out_of_date(SENT_ORDINARY + timedelta(hours=5), SENT_ORDINARY) is False


@pytest.mark.parametrize("which", ["as_of", "sent_at"])
def test_a_naive_instant_is_refused(which: str) -> None:
    naive = datetime(2026, 10, 23, 11, 0)
    with pytest.raises(ValidationFailed) as refused:
        if which == "as_of":
            figure_is_out_of_date(naive, SENT_ORDINARY)
        else:
            figure_is_out_of_date(SENT_ORDINARY, naive)
    assert refused.value.field == which


_INSTANTS = st.datetimes(
    min_value=datetime(2026, 1, 1), max_value=datetime(2027, 1, 1), timezones=st.just(UTC)
)
_AGES = st.timedeltas(min_value=timedelta(0), max_value=timedelta(days=3))


@given(sent_at=_INSTANTS, age=_AGES)
def test_property_out_of_date_is_exactly_older_than_the_window(
    sent_at: datetime, age: timedelta
) -> None:
    assert figure_is_out_of_date(sent_at - age, sent_at) is (age > CONFIRMABLE_FIGURE_AGE)


@given(sent_at=_INSTANTS, younger=_AGES, extra=_AGES)
def test_property_an_older_figure_is_never_fresher(
    sent_at: datetime, younger: timedelta, extra: timedelta
) -> None:
    fresh = figure_is_out_of_date(sent_at - younger, sent_at)
    older = figure_is_out_of_date(sent_at - younger - extra, sent_at)
    assert not (fresh and not older)


@given(sent_at=_INSTANTS, age=_AGES)
def test_property_the_verdict_does_not_depend_on_the_zone_the_instants_are_written_in(
    sent_at: datetime, age: timedelta
) -> None:
    as_of = sent_at - age
    assert figure_is_out_of_date(
        as_of.astimezone(LONDON), sent_at.astimezone(LONDON)
    ) is figure_is_out_of_date(as_of, sent_at)


# --- the record-order test behind hazard H-32 ----------------------------------------------------


def _report(written_at: datetime | None, effective_at: datetime) -> CapacityReport:
    return CapacityReport(
        id="r",
        service_id="s",
        value=7,
        measure=Measure.REFERRALS_ACCEPTABLE,
        effective_at=effective_at,
        source=ReportSource.ADVISOR_PHONED,
        report_type=ReportType.NUMBER,
        written_at=written_at,
    )


@pytest.mark.parametrize(
    ("sent_microsecond", "written_second", "since"),
    [
        (0, -1, False),  # written the second before the prompt
        (0, 0, True),  # the same whole second: a tie fails closed
        (0, 1, True),  # the second after
        (500_000, -1, False),
        (500_000, 0, True),  # the stamp is the whole second the prompt was sent in
        (999_999, 0, True),
        (500_000, 1, True),
    ],
)
def test_a_report_is_since_the_prompt_by_the_whole_second_of_its_write(
    sent_microsecond: int, written_second: int, since: bool
) -> None:
    sent_at = SENT_ORDINARY.replace(microsecond=sent_microsecond)
    written_at = SENT_ORDINARY + timedelta(seconds=written_second)
    # The effective time is a day before the prompt: the answer cannot come from it.
    report = _report(written_at, SENT_ORDINARY - timedelta(days=1))

    assert recorded_since_prompt(report, sent_at) is since


def test_the_effective_time_does_not_decide_whether_a_report_is_since_the_prompt() -> None:
    written_before = _report(SENT_ORDINARY - timedelta(hours=1), SENT_ORDINARY + timedelta(hours=1))
    written_after = _report(
        SENT_ORDINARY + timedelta(minutes=3), SENT_ORDINARY - timedelta(hours=1)
    )

    assert recorded_since_prompt(written_before, SENT_ORDINARY) is False
    assert recorded_since_prompt(written_after, SENT_ORDINARY) is True


def test_a_report_with_no_write_time_counts_as_since_the_prompt() -> None:
    """Fail closed: a report the store has not stamped cannot be shown to predate the prompt."""
    assert recorded_since_prompt(_report(None, SENT_ORDINARY - timedelta(days=1)), SENT_ORDINARY)


def test_write_times_are_compared_as_utc_instants() -> None:
    """The prompt at 00:30 London (GMT, 00:30Z) on the spring change day, against write times in
    Athens (02:30 EET is 00:30Z; the clock there changes at 03:00, after both)."""
    sent_at = datetime(2026, 3, 29, 0, 30, tzinfo=LONDON)
    athens = ZoneInfo("Europe/Athens")
    effective = sent_at - timedelta(days=1)

    same = _report(datetime(2026, 3, 29, 2, 30, tzinfo=athens), effective)
    before = _report(datetime(2026, 3, 29, 2, 29, 59, tzinfo=athens), effective)

    assert recorded_since_prompt(same, sent_at) is True
    assert recorded_since_prompt(before, sent_at) is False


@pytest.mark.parametrize("which", ["written_at", "sent_at"])
def test_a_naive_instant_is_refused_by_the_record_order_test(which: str) -> None:
    naive = datetime(2026, 10, 23, 11, 0)
    report = _report(naive if which == "written_at" else SENT_ORDINARY, SENT_ORDINARY)
    with pytest.raises(ValidationFailed) as refused:
        recorded_since_prompt(report, naive if which == "sent_at" else SENT_ORDINARY)
    assert refused.value.field == which
