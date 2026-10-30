"""The schedule with bank holidays and service closures (TEN-066, H-T21): a closed local day has no
due time, next_due skips it, and the closure is the tenant's region plus the service's own periods.
The profile is UCR West's (Monday to Friday, 08:00 to 20:00 London local, every 2 hours), as in
test_schedule.py. Instants are UTC; London is on GMT in January and BST in April.
"""

from datetime import UTC, date, datetime, time

from diucs.domain.codes import Cadence, Channel, Measure, ServiceCategory
from diucs.domain.model.service import AvailableTime, ServiceProfile
from diucs.domain.rules.holidays import ClosurePeriod, closed_on
from diucs.domain.rules.schedule import current_due, due_times_on, next_due

ENGLAND_AND_WALES = "england-and-wales"
SCOTLAND = "scotland"


def ucr_west() -> ServiceProfile:
    return ServiceProfile(
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


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def test_a_bank_holiday_has_no_due_times_when_the_nation_closes() -> None:
    """Easter Monday 2026 is a holiday in England and Wales: no prompt, and no due time."""
    easter_monday = date(2026, 4, 6)
    assert due_times_on(ucr_west(), easter_monday, closed=closed_on(ENGLAND_AND_WALES)) == []


def test_the_same_day_is_due_where_its_nation_is_open() -> None:
    easter_monday = date(2026, 4, 6)
    assert due_times_on(ucr_west(), easter_monday, closed=closed_on(SCOTLAND)) != []


def test_with_no_closure_the_schedule_is_unchanged() -> None:
    friday = date(2026, 10, 30)
    assert due_times_on(ucr_west(), friday) == due_times_on(ucr_west(), friday, closed=None)
    assert due_times_on(ucr_west(), friday) != []


def test_a_bank_holiday_closure_suppresses_prompts() -> None:
    """Good Friday 2026 (3 April) and Easter Monday (6 April) are closed in England and Wales. A
    report due on the Thursday evening is followed by the first due time on Tuesday 7 April, not by
    the Friday or the Monday (H-T21)."""
    now = utc(2026, 4, 2, 19, 30)  # Thursday, after its last due time (20:00 BST)
    open_schedule = next_due(ucr_west(), now)
    closed = next_due(ucr_west(), now, closed=closed_on(ENGLAND_AND_WALES))
    assert open_schedule == utc(2026, 4, 3, 7, 0)
    assert closed == utc(2026, 4, 7, 7, 0)


def test_current_due_does_not_look_back_to_a_closed_day() -> None:
    """On Easter Monday morning, before the first due time, the most recent due time is Thursday's:
    the closed Friday and Monday have none."""
    now = utc(2026, 4, 6, 6, 0)
    assert current_due(ucr_west(), now, closed=closed_on(ENGLAND_AND_WALES)) == utc(
        2026, 4, 2, 19, 0
    )


def test_a_service_closure_period_is_honoured_on_each_closed_day() -> None:
    closures = [ClosurePeriod(first=date(2026, 4, 7), last=date(2026, 4, 8))]
    closed = closed_on(ENGLAND_AND_WALES, closures)
    assert due_times_on(ucr_west(), date(2026, 4, 7), closed=closed) == []
    assert due_times_on(ucr_west(), date(2026, 4, 8), closed=closed) == []
    assert due_times_on(ucr_west(), date(2026, 4, 9), closed=closed) != []


def test_a_closure_is_read_on_the_local_day_the_window_starts() -> None:
    """The closed predicate takes the local day the schedule uses for the window (in its zone), so
    a 19:00 BST due time on a closed day is suppressed as the day is."""
    closures = [ClosurePeriod(first=date(2026, 9, 1), last=date(2026, 9, 1))]
    closed = closed_on(ENGLAND_AND_WALES, closures)
    assert due_times_on(ucr_west(), date(2026, 9, 1), closed=closed) == []
    assert due_times_on(ucr_west(), date(2026, 9, 2), closed=closed) != []


def test_the_tenant_region_decides_which_holidays_close_the_schedule() -> None:
    """2 January 2026 is a holiday in Scotland and not in England and Wales."""
    day = date(2026, 1, 2)
    assert due_times_on(ucr_west(), day, closed=closed_on(SCOTLAND)) == []
    assert due_times_on(ucr_west(), day, closed=closed_on(ENGLAND_AND_WALES)) != []
