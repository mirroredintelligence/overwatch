"""How long a projected status stays true: `next_status_change` (TEN-056, DEC-132 item 4, audit F
section 4.7 "staleness").

The producer puts the answer on a capacity projection as `valid_until`: the next instant at which
the status computed from the same inputs could change with no new report (a reply-by passing, the
service opening or closing, the figure growing old enough to warn). The oracle of this file is the
status rule itself: between `now` and `valid_until` the status, the overdue flag and the stale
warning computed by `compute_status` do not change, so a read before `valid_until` never shows a
status that the member's own board would already have moved on from.
"""

from datetime import UTC, datetime, timedelta

import pytest

from diucs.domain.model.tenant_policy import DEFAULT_POLICY
from diucs.domain.rules.projection_validity import next_status_change
from diucs.domain.rules.status import compute_status
from tests.support.projection_samples import (
    REPORTED_AT,
    sample_policy,
    sample_profile,
    sample_report,
)

NOW = datetime(2026, 10, 29, 9, 30, tzinfo=UTC)  # a Thursday, GMT: London is UTC


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=UTC)


def test_a_fresh_report_stays_true_until_the_next_reply_by_passes() -> None:
    # Every two hours from 08:00: the 10:00 prompt has until 10:30 to be answered.
    assert next_status_change(sample_profile(), REPORTED_AT, NOW) == at(29, 10, 30)


def test_the_stale_warning_is_a_boundary_when_it_comes_first() -> None:
    # Reported at 09:00, warned after two hours (11:00); the reply-by of 12:00 is 12:30. The 10:30
    # one is passed, so the 10:40 reader meets 11:00 first.
    assert next_status_change(sample_profile(), REPORTED_AT, at(29, 10, 40)) == at(29, 11, 0)


def test_closing_time_is_a_boundary() -> None:
    profile = sample_profile()
    report = at(29, 17, 50)
    # 17:55: the 18:00 prompt's reply-by is 18:30, the closing is 18:00, the warning 19:50.
    assert next_status_change(profile, report, at(29, 17, 55)) == at(29, 18, 0)


def test_when_closed_the_next_opening_is_the_boundary() -> None:
    # Thursday 19:00 is out of hours. The next opening is Friday 08:00.
    assert next_status_change(sample_profile(), at(29, 17, 0), at(29, 19, 0)) == at(30, 8, 0)


def test_a_service_that_never_reported_is_already_overdue_so_only_the_hours_can_change_it() -> None:
    # The 08:00 prompt was missed at 08:30 and nothing was ever reported: Not updated until a report
    # arrives, which is an event. Only the closing at 18:00 could change what the board says.
    assert next_status_change(sample_profile(), None, NOW) == at(29, 18, 0)


def test_a_suspended_service_has_no_time_boundary() -> None:
    assert next_status_change(sample_profile(suspended=True), REPORTED_AT, NOW) is None


def test_the_tenant_reply_window_moves_the_boundary() -> None:
    policy = sample_policy(
        reply_window=timedelta(minutes=45),
        reminder_after=timedelta(minutes=45),
        phone_task_after=timedelta(minutes=75),
        escalate_after=timedelta(minutes=105),
    )
    assert next_status_change(sample_profile(), REPORTED_AT, NOW, policy) == at(29, 10, 45)


def test_a_naive_instant_is_refused() -> None:
    with pytest.raises(ValueError):
        next_status_change(sample_profile(), REPORTED_AT, datetime(2026, 10, 29, 9, 30))


def test_a_report_after_now_is_refused() -> None:
    with pytest.raises(ValueError):
        next_status_change(sample_profile(), at(29, 10, 0), NOW)


def _state_key(profile, report, when):  # type: ignore[no-untyped-def]
    state = compute_status(profile, report, (), when, DEFAULT_POLICY)
    return (state.status, state.freshness.overdue, state.freshness.stale_warning)


def test_the_status_does_not_change_before_the_boundary() -> None:
    """The oracle: every status input the rule reads is constant on [now, valid_until)."""
    profile = sample_profile()
    report = sample_report()
    moment = at(26, 0, 0) + timedelta(hours=9)  # the Monday after the reported instant
    reported = sample_report(effective_at=moment)
    end = at(31, 0, 0)
    checked = 0
    now = moment + timedelta(minutes=1)
    while now < end:
        until = next_status_change(profile, reported.effective_at, now)
        assert until is not None and until > now
        assert _state_key(profile, reported, now) == _state_key(
            profile, reported, until - timedelta(microseconds=1)
        )
        checked += 1
        now += timedelta(minutes=37)
    assert checked > 100
    assert report.effective_at == REPORTED_AT


def test_the_status_can_change_at_the_boundary() -> None:
    """The boundary is not padding: at some boundary of a day the state really changes."""
    profile = sample_profile()
    reported = sample_report(effective_at=at(29, 9, 0))
    changed = 0
    now = at(29, 9, 30)
    while now < at(30, 20, 0):
        until = next_status_change(profile, reported.effective_at, now)
        assert until is not None
        if _state_key(profile, reported, until) != _state_key(profile, reported, now):
            changed += 1
        now = until
    assert changed >= 4


def test_two_windows_that_join_are_one_stretch_of_hours() -> None:
    from datetime import time

    from diucs.domain.model.service import AvailableTime
    from diucs.domain.rules.opening_hours import next_hours_change

    joined = (
        AvailableTime.weekdays(time(8, 0), time(12, 0)),
        AvailableTime.weekdays(time(12, 0), time(18, 0)),
    )
    assert next_hours_change(joined, at(29, 9, 0)) == at(29, 18, 0)
    assert next_hours_change((), at(29, 9, 0)) is None
