"""Tests for diucs.domain.rules.alerts: alert triggers, subscriptions, quiet hours, escalation (D24).

Rule: docs/spec/domain-rules.md section 8, and the D24 prompt. Instants are written as London
wall-clock times through london_to_utc, so each test reads as a London time in both seasons.
Clock-change tests use 2026-03-29 and 2026-10-25 (lessons L4, L25, L52). Plain strings and members
of other enums are refused (DEC-040, lessons L3 and L38).
"""

from dataclasses import fields, replace
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from typing import Final

import pytest
from hypothesis import given
from hypothesis import strategies as st

from diucs.domain.codes import AlertKind, Status
from diucs.domain.errors import ValidationFailed
from diucs.domain.rules.alerts import (
    ESCALATION_LADDER,
    Alert,
    AlertPreferences,
    alert_for_pressure,
    alerts_for_change,
    default_preferences,
    escalation_at,
    next_escalation_target,
    not_updated_alert_due,
    should_notify,
)
from diucs.domain.rules.london_time import london_to_utc, to_london
from diucs.domain.rules.pressure import Pressure

SERVICE: Final = "svc-0001"
SUMMER: Final = date(2026, 7, 10)  # British Summer Time
WINTER: Final = date(2026, 1, 15)  # GMT
SPRING_CHANGE: Final = date(2026, 3, 29)  # clocks go forward 01:00 to 02:00
AUTUMN_CHANGE: Final = date(2026, 10, 25)  # clocks go back 02:00 to 01:00
QUIET: Final = (time(22, 0), time(6, 0))


def at(d: date, hh: int, mm: int = 0) -> datetime:
    return london_to_utc(d, time(hh, mm))


def prefs(**changes: object) -> AlertPreferences:
    return replace(default_preferences(), **changes)


class OtherStatus(StrEnum):
    NOT_ACCEPTING = "not-accepting"


# Defaults and preferences validation


def test_default_preferences_match_the_rule_book() -> None:
    p = default_preferences()
    assert p.kinds == frozenset(AlertKind)
    assert p.not_updated_hours == 2
    assert p.quiet_hours is None
    assert p.quiet_critical_only is True
    assert p.ack_minutes == 15


@pytest.mark.parametrize("ack", [10, 15, 30])
def test_allowed_ack_windows_are_accepted(ack: int) -> None:
    assert prefs(ack_minutes=ack).ack_minutes == ack


def test_ack_window_of_twenty_minutes_is_refused() -> None:
    with pytest.raises(ValidationFailed) as err:
        AlertPreferences(
            kinds=frozenset(AlertKind),
            not_updated_hours=2,
            quiet_hours=None,
            quiet_critical_only=True,
            ack_minutes=20,
        )
    assert err.value.field == "ack_minutes"


@pytest.mark.parametrize("hours", [1, 3, 6])
def test_not_updated_hours_other_than_two_or_four_are_refused(hours: int) -> None:
    with pytest.raises(ValidationFailed) as err:
        prefs(not_updated_hours=hours)
    assert err.value.field == "not_updated_hours"


@pytest.mark.parametrize("quiet", [(time(21, 0), time(6, 0)), (time(22, 0), time(7, 0))])
def test_quiet_hours_other_than_22_to_06_are_refused(quiet: tuple[time, time]) -> None:
    with pytest.raises(ValidationFailed) as err:
        prefs(quiet_hours=quiet)
    assert err.value.field == "quiet_hours"


def test_kinds_must_be_alert_kind_members() -> None:
    with pytest.raises(ValidationFailed) as err:
        prefs(kinds=frozenset({"service-closed"}))
    assert err.value.field == "kinds"


def test_alert_carries_no_free_text() -> None:
    assert [f.name for f in fields(Alert)] == ["kind", "service_id", "raised_at", "critical"]


@pytest.mark.parametrize(
    ("kind", "service_id", "critical"),
    [
        (AlertKind.SYSTEM_PRESSURE, SERVICE, True),  # pressure carries no service
        (AlertKind.SERVICE_CLOSED, None, True),  # a service alert names its service
        (AlertKind.SERVICE_CLOSED, SERVICE, False),  # critical follows the kind
    ],
)
def test_alert_fields_must_match_their_kind(kind: AlertKind, service_id: str | None, critical: bool) -> None:
    with pytest.raises(ValidationFailed):
        Alert(kind, service_id, at(SUMMER, 14), critical)


# Service triggers: service-closed and over-capacity (rule 1)


def test_moving_to_not_accepting_in_hours_is_one_critical_alert() -> None:
    now = at(SUMMER, 14, 12)
    alerts = alerts_for_change(SERVICE, Status.ACCEPTING, Status.NOT_ACCEPTING, True, now)
    assert alerts == [Alert(AlertKind.SERVICE_CLOSED, SERVICE, now, True)]


def test_planned_out_of_hours_closure_raises_nothing() -> None:
    now = at(SUMMER, 19, 0)
    assert alerts_for_change(SERVICE, Status.ACCEPTING, Status.NOT_ACCEPTING, False, now) == []


@pytest.mark.parametrize(
    "before", [Status.ACCEPTING, Status.LIMITED, Status.OVER_CAPACITY, Status.NOT_UPDATED, Status.OUT_OF_HOURS, None]
)
def test_service_closed_fires_from_any_other_status(before: Status | None) -> None:
    alerts = alerts_for_change(SERVICE, before, Status.NOT_ACCEPTING, True, at(SUMMER, 10))
    assert [a.kind for a in alerts] == [AlertKind.SERVICE_CLOSED]


def test_moving_to_over_capacity_is_one_non_critical_alert() -> None:
    now = at(SUMMER, 13, 10)
    alerts = alerts_for_change(SERVICE, Status.LIMITED, Status.OVER_CAPACITY, True, now)
    assert alerts == [Alert(AlertKind.OVER_CAPACITY, SERVICE, now, False)]


def test_over_capacity_to_over_capacity_raises_nothing() -> None:
    assert alerts_for_change(SERVICE, Status.OVER_CAPACITY, Status.OVER_CAPACITY, True, at(SUMMER, 14)) == []


def test_not_accepting_to_not_accepting_raises_nothing_no_repeat() -> None:
    assert alerts_for_change(SERVICE, Status.NOT_ACCEPTING, Status.NOT_ACCEPTING, True, at(SUMMER, 14)) == []


def test_a_change_to_accepting_raises_nothing() -> None:
    assert alerts_for_change(SERVICE, Status.LIMITED, Status.ACCEPTING, True, at(SUMMER, 14)) == []


def test_blank_service_id_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        alerts_for_change("", Status.ACCEPTING, Status.NOT_ACCEPTING, True, at(SUMMER, 14))


def test_status_from_another_enum_with_the_same_value_is_refused() -> None:
    with pytest.raises(TypeError):
        alerts_for_change(SERVICE, Status.ACCEPTING, OtherStatus.NOT_ACCEPTING, True, at(SUMMER, 14))  # type: ignore[arg-type]


def test_plain_string_status_is_refused() -> None:
    with pytest.raises(TypeError):
        alerts_for_change(SERVICE, "accepting", Status.NOT_ACCEPTING, True, at(SUMMER, 14))  # type: ignore[arg-type]


# System pressure trigger (rule 4)


def test_watch_to_high_is_one_critical_pressure_alert() -> None:
    now = at(SUMMER, 14, 12)
    assert alert_for_pressure(Pressure.WATCH, Pressure.HIGH, now) == Alert(
        AlertKind.SYSTEM_PRESSURE, None, now, True
    )


def test_normal_to_high_is_also_critical() -> None:
    now = at(SUMMER, 14, 12)
    assert alert_for_pressure(Pressure.NORMAL, Pressure.HIGH, now) == Alert(
        AlertKind.SYSTEM_PRESSURE, None, now, True
    )


def test_high_to_high_raises_nothing() -> None:
    assert alert_for_pressure(Pressure.HIGH, Pressure.HIGH, at(SUMMER, 14)) is None


@pytest.mark.parametrize(("before", "after"), [(Pressure.HIGH, Pressure.WATCH), (Pressure.WATCH, Pressure.NORMAL)])
def test_easing_pressure_raises_nothing(before: Pressure, after: Pressure) -> None:
    assert alert_for_pressure(before, after, at(SUMMER, 14)) is None


def test_plain_string_pressure_is_refused() -> None:
    with pytest.raises(TypeError):
        alert_for_pressure("watch", Pressure.HIGH, at(SUMMER, 14))  # type: ignore[arg-type]


# Not updated (rule 3)


def test_two_hour_threshold_is_due_at_exactly_two_hours_in_summer() -> None:
    since = at(SUMMER, 12, 0)
    assert not_updated_alert_due(since, 2, at(SUMMER, 13, 59)) is False
    assert not_updated_alert_due(since, 2, at(SUMMER, 14, 0)) is True


def test_four_hour_threshold_is_not_due_at_two_hours() -> None:
    since = at(SUMMER, 12, 0)
    assert not_updated_alert_due(since, 4, at(SUMMER, 14, 0)) is False
    assert not_updated_alert_due(since, 4, at(SUMMER, 16, 0)) is True


def test_two_hour_threshold_in_winter() -> None:
    since = at(WINTER, 12, 0)
    assert not_updated_alert_due(since, 2, at(WINTER, 13, 59)) is False
    assert not_updated_alert_due(since, 2, at(WINTER, 14, 0)) is True


def test_elapsed_time_across_spring_change_is_real_time_not_wall_clock() -> None:
    # 00:30 GMT to 03:00 BST is 1 hour 30 minutes of real time, though the wall clock reads 2 h 30.
    since = at(SPRING_CHANGE, 0, 30)
    assert not_updated_alert_due(since, 2, at(SPRING_CHANGE, 3, 0)) is False
    assert not_updated_alert_due(since, 2, at(SPRING_CHANGE, 4, 30)) is True


def test_hours_other_than_two_or_four_are_refused_for_the_check() -> None:
    with pytest.raises(ValidationFailed):
        not_updated_alert_due(at(SUMMER, 12), 3, at(SUMMER, 14))


# Quiet hours and subscriptions


def _over_capacity(now: datetime) -> Alert:
    return Alert(AlertKind.OVER_CAPACITY, SERVICE, now, False)


def _service_closed(now: datetime) -> Alert:
    return Alert(AlertKind.SERVICE_CLOSED, SERVICE, now, True)


def test_over_capacity_at_2330_in_summer_is_not_sent_in_quiet_hours() -> None:
    now = at(SUMMER, 23, 30)
    assert should_notify(prefs(quiet_hours=QUIET), _over_capacity(now), now) is False


def test_service_closed_at_2330_in_summer_is_sent_in_quiet_hours() -> None:
    now = at(SUMMER, 23, 30)
    assert should_notify(prefs(quiet_hours=QUIET), _service_closed(now), now) is True


def test_over_capacity_at_2330_in_winter_is_not_sent_in_quiet_hours() -> None:
    now = at(WINTER, 23, 30)
    assert should_notify(prefs(quiet_hours=QUIET), _over_capacity(now), now) is False


def test_quiet_window_ends_exactly_at_six_in_summer_and_winter() -> None:
    p = prefs(quiet_hours=QUIET)
    for day in (SUMMER, WINTER):
        assert should_notify(p, _over_capacity(at(day, 5, 59)), at(day, 5, 59)) is False
        assert should_notify(p, _over_capacity(at(day, 6, 0)), at(day, 6, 0)) is True


def test_quiet_window_starts_exactly_at_twenty_two_in_summer_and_winter() -> None:
    p = prefs(quiet_hours=QUIET)
    for day in (SUMMER, WINTER):
        assert should_notify(p, _over_capacity(at(day, 21, 59)), at(day, 21, 59)) is True
        assert should_notify(p, _over_capacity(at(day, 22, 0)), at(day, 22, 0)) is False


def test_quiet_window_across_the_spring_change() -> None:
    p = prefs(quiet_hours=QUIET)
    # 23:00 on the evening before, and 03:30 on the change night, are both quiet.
    assert should_notify(p, _over_capacity(at(SPRING_CHANGE, 3, 30)), at(SPRING_CHANGE, 3, 30)) is False
    # 05:59 BST is quiet; 06:00 BST is the end of the window.
    assert should_notify(p, _over_capacity(at(SPRING_CHANGE, 5, 59)), at(SPRING_CHANGE, 5, 59)) is False
    assert should_notify(p, _over_capacity(at(SPRING_CHANGE, 6, 0)), at(SPRING_CHANGE, 6, 0)) is True


def test_quiet_window_across_the_autumn_change() -> None:
    p = prefs(quiet_hours=QUIET)
    evening = at(AUTUMN_CHANGE - timedelta(days=1), 23, 30)
    assert should_notify(p, _over_capacity(evening), evening) is False
    # The repeated 01:30 is the first occurrence (BST), which is inside the window.
    assert should_notify(p, _over_capacity(at(AUTUMN_CHANGE, 1, 30)), at(AUTUMN_CHANGE, 1, 30)) is False
    assert should_notify(p, _over_capacity(at(AUTUMN_CHANGE, 5, 59)), at(AUTUMN_CHANGE, 5, 59)) is False
    assert should_notify(p, _over_capacity(at(AUTUMN_CHANGE, 6, 0)), at(AUTUMN_CHANGE, 6, 0)) is True


def test_everything_during_quiet_hours_sends_non_critical_alerts() -> None:
    now = at(SUMMER, 23, 30)
    p = prefs(quiet_hours=QUIET, quiet_critical_only=False)
    assert should_notify(p, _over_capacity(now), now) is True


def test_no_quiet_hours_sends_at_night() -> None:
    now = at(SUMMER, 23, 30)
    assert should_notify(prefs(quiet_hours=None), _over_capacity(now), now) is True


def test_kind_not_in_preferences_is_never_sent() -> None:
    now = at(SUMMER, 14)
    assert should_notify(prefs(kinds=frozenset({AlertKind.SERVICE_CLOSED})), _over_capacity(now), now) is False
    assert should_notify(prefs(kinds=frozenset({AlertKind.SERVICE_CLOSED})), _service_closed(now), now) is True


@given(
    now=st.datetimes(
        min_value=datetime(2026, 1, 1),
        max_value=datetime(2027, 1, 1),
        timezones=st.just(UTC),
    )
)
def test_quiet_critical_only_matches_the_london_wall_clock(now: datetime) -> None:
    # 22:00 and 06:00 are not in the 01:00-02:00 change hour, so a wall-clock oracle is exact here.
    local = to_london(now).time()
    in_quiet = local >= time(22, 0) or local < time(6, 0)
    p = prefs(quiet_hours=QUIET, quiet_critical_only=True)
    assert should_notify(p, _over_capacity(now), now) is (not in_quiet)
    assert should_notify(p, _service_closed(now), now) is True


def test_naive_datetimes_are_refused() -> None:
    naive = datetime(2026, 7, 10, 23, 30)
    with pytest.raises(ValueError):
        should_notify(prefs(), _over_capacity(at(SUMMER, 23, 30)), naive)
    with pytest.raises(ValueError):
        escalation_at(naive, prefs())
    with pytest.raises(ValueError):
        not_updated_alert_due(naive, 2, at(SUMMER, 14))
    with pytest.raises(ValueError):
        alerts_for_change(SERVICE, Status.ACCEPTING, Status.NOT_ACCEPTING, True, naive)
    with pytest.raises(ValueError):
        alert_for_pressure(Pressure.WATCH, Pressure.HIGH, naive)


# Escalation


def test_escalation_is_ack_window_after_the_alert_was_sent() -> None:
    # Alerted 14:12 (BST), no acknowledgement in 15 minutes: escalate at 14:27.
    assert escalation_at(at(SUMMER, 14, 12), prefs(ack_minutes=15)) == at(SUMMER, 14, 27)


@pytest.mark.parametrize(("ack", "expected"), [(10, (14, 22)), (30, (14, 42))])
def test_escalation_follows_the_chosen_window(ack: int, expected: tuple[int, int]) -> None:
    assert escalation_at(at(SUMMER, 14, 12), prefs(ack_minutes=ack)) == at(SUMMER, *expected)


def test_escalation_across_the_autumn_change_adds_real_minutes() -> None:
    # 01:50 BST (first occurrence) plus 15 real minutes ends at 01:05 GMT. Escalation adds real time.
    sent = at(AUTUMN_CHANGE, 1, 50)
    assert escalation_at(sent, prefs(ack_minutes=15)) == sent + timedelta(minutes=15)


def test_escalation_ladder_order() -> None:
    assert ESCALATION_LADDER == ("subscriber", "deputy", "shift-lead")


@pytest.mark.parametrize(
    ("current", "expected"),
    [("subscriber", "deputy"), ("deputy", "shift-lead"), ("shift-lead", None)],
)
def test_next_escalation_target(current: str, expected: str | None) -> None:
    assert next_escalation_target(current) == expected


def test_unknown_escalation_stage_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        next_escalation_target("boss")
