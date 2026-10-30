"""The time zone is an explicit argument of the time rules (TEN-065, DEC-136 item 13, audit F).

A tenant (and a network) has a time zone, validated against an allow-list that holds only
Europe/London today. The rules take it as a value and never look it up; the default is London, so
every caller that has not been given a zone yet behaves as before, and a ratchet lists those
callers. The allow-list is enforced where a zone is made from a name (`zone_named`) and on the
tenant record, so the rules themselves accept any `ZoneInfo`: that is what lets these tests show
the zone is really used, with a zone that is not London.
"""

import ast
import re
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any, Final
from zoneinfo import ZoneInfo

import pytest

from diucs.domain.codes import (
    AlertKind,
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
from diucs.domain.model.tenant_policy import DEFAULT_POLICY
from diucs.domain.rules.alerts import Alert, AlertPreferences, should_notify
from diucs.domain.rules.freshness import assess_freshness
from diucs.domain.rules.london_time import LONDON
from diucs.domain.rules.schedule import current_due, due_times_on, next_due
from diucs.domain.rules.status import compute_status

NEW_YORK = ZoneInfo("America/New_York")
TOKYO = ZoneInfo("Asia/Tokyo")

DAILY = ServiceProfile(
    id="svc-daily",
    name="Daily Service",
    category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
    measure=Measure.REFERRALS_ACCEPTABLE,
    unit_label="referrals",
    established_capacity=8,
    can_exceed_established=False,
    usual_range=(0, 8),
    cadence=Cadence.ONCE_A_DAY,
    available_times=(AvailableTime.every_day(time(9, 0), time(17, 0)),),
    channel=Channel.TEXT,
    limited_level_percent=80,
)


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def _report(at: datetime, value: int = 4) -> CapacityReport:
    return CapacityReport(
        id="obs-1",
        service_id=DAILY.id,
        value=value,
        measure=DAILY.measure,
        effective_at=at,
        source=ReportSource.TEXT,
        report_type=ReportType.NUMBER,
    )


# -- schedule ------------------------------------------------------------------------


def test_the_due_time_is_in_the_zone_given() -> None:
    day = date(2026, 7, 1)
    assert due_times_on(DAILY, day, DEFAULT_POLICY, NEW_YORK) == [utc(2026, 7, 1, 13, 0)]
    assert due_times_on(DAILY, day, DEFAULT_POLICY, TOKYO) == [utc(2026, 7, 1, 0, 0)]
    assert due_times_on(DAILY, day, DEFAULT_POLICY, LONDON) == [utc(2026, 7, 1, 8, 0)]


def test_without_a_zone_the_due_time_is_londons() -> None:
    day = date(2026, 7, 1)
    assert due_times_on(DAILY, day) == due_times_on(DAILY, day, DEFAULT_POLICY, LONDON)
    assert due_times_on(DAILY, day, zone=NEW_YORK) == due_times_on(
        DAILY, day, DEFAULT_POLICY, NEW_YORK
    )


def test_the_next_and_the_current_due_follow_the_zone() -> None:
    now = utc(2026, 7, 1, 12, 0)
    assert next_due(DAILY, now, DEFAULT_POLICY, NEW_YORK) == utc(2026, 7, 1, 13, 0)
    assert next_due(DAILY, now, DEFAULT_POLICY, LONDON) == utc(2026, 7, 2, 8, 0)
    assert current_due(DAILY, now, DEFAULT_POLICY, NEW_YORK) == utc(2026, 6, 30, 13, 0)
    assert current_due(DAILY, now, DEFAULT_POLICY, LONDON) == utc(2026, 7, 1, 8, 0)


@pytest.mark.parametrize("bad", [None, "Europe/London", "America/New_York", UTC, 0])
def test_a_zone_that_is_not_a_zoneinfo_is_refused(bad: object) -> None:
    with pytest.raises(TypeError, match="a ZoneInfo is required"):
        next_due(DAILY, utc(2026, 7, 1, 12, 0), DEFAULT_POLICY, bad)  # type: ignore[arg-type]


# -- freshness and status ------------------------------------------------------------


def test_a_missed_prompt_is_judged_in_the_zone_given() -> None:
    # Reported 14:00Z on 30 June. London's 08:00Z prompt of 1 July has been missed by 13:10Z; New
    # York's is not due until 13:00Z and its window has not run out, so nothing is overdue there.
    last = utc(2026, 6, 30, 14, 0)
    now = utc(2026, 7, 1, 13, 10)
    assert assess_freshness(DAILY, last, now, DEFAULT_POLICY, LONDON).overdue is True
    assert assess_freshness(DAILY, last, now, DEFAULT_POLICY, NEW_YORK).overdue is False
    assert assess_freshness(DAILY, last, now).overdue is True


def test_the_status_follows_the_zone() -> None:
    last = utc(2026, 6, 30, 14, 0)
    now = utc(2026, 7, 1, 13, 10)
    in_london = compute_status(DAILY, _report(last), (), now, DEFAULT_POLICY, LONDON)
    in_new_york = compute_status(DAILY, _report(last), (), now, DEFAULT_POLICY, NEW_YORK)
    assert in_london.status is Status.NOT_UPDATED
    assert in_new_york.status is Status.ACCEPTING
    assert compute_status(DAILY, _report(last), (), now).status is Status.NOT_UPDATED


def test_the_opening_hours_in_the_status_follow_the_zone() -> None:
    # 08:30Z is 09:30 in London (open) and 04:30 in New York (closed).
    now = utc(2026, 7, 1, 8, 30)
    report = _report(utc(2026, 7, 1, 8, 5))
    assert compute_status(DAILY, report, (), now, DEFAULT_POLICY, LONDON).status is not (
        Status.OUT_OF_HOURS
    )
    assert (
        compute_status(DAILY, report, (), now, DEFAULT_POLICY, NEW_YORK).status
        is Status.OUT_OF_HOURS
    )


# -- quiet hours ---------------------------------------------------------------------


def test_quiet_hours_are_the_tenants_night() -> None:
    from diucs.domain.rules.alerts import QUIET_END, QUIET_START

    prefs = AlertPreferences(
        kinds=frozenset(AlertKind),
        not_updated_hours=2,
        quiet_hours=(QUIET_START, QUIET_END),
        quiet_critical_only=True,
        ack_minutes=15,
    )
    alert = Alert(AlertKind.NOT_UPDATED, "svc-daily", utc(2026, 7, 1, 23, 0), False)
    now = utc(2026, 7, 1, 23, 0)  # 00:00 in London (night), 19:00 in New York (evening)
    assert should_notify(prefs, alert, now) is False
    assert should_notify(prefs, alert, now, LONDON) is False
    assert should_notify(prefs, alert, now, NEW_YORK) is True


# -- the ratchet ---------------------------------------------------------------------

# The position of the `zone` argument of each rule that takes one, counting from zero.
ZONE_POSITION: Final = {
    "is_in_hours": 2,
    "next_opening": 2,
    "due_times_on": 3,
    "next_due": 3,
    "current_due": 3,
    "assess_freshness": 4,
    "compute_status": 5,
    "should_notify": 3,
    "format_hhmm": 1,
    "format_stamp": 1,
}
SOURCE_ROOT: Final = Path(__file__).resolve().parents[4] / "src" / "diucs"

# Callers that do not yet pass the tenant's zone, each with the task that does (the builder's
# reading of the tenancy plan: TEN-026 gives the use cases the configuration read port that carries
# the tenant's zone). Every entry must still offend: a converted caller is removed, so the list only
# shrinks. The rules that take a zone pass it on; `network_board` has no zone to pass because a
# projection holds none (the source tenant's zone would join the projection allowlist, TEN-057).
ZONE_NOT_YET_THREADED: dict[str, str] = {
    "application/use_cases/approve_registration.py": "TEN-026",
    "application/use_cases/cancel_booking.py": "TEN-026",
    "application/use_cases/handle_inbound_text.py": "TEN-026",
    "application/use_cases/query_board.py": "TEN-039",
    "application/use_cases/report_capacity.py": "TEN-026",
    "application/use_cases/request_booking.py": "TEN-026",
    "application/use_cases/resolve_report_flag.py": "TEN-026",
    "application/use_cases/respond_to_booking.py": "TEN-026",
    "application/use_cases/setup_service_by_lead.py": "TEN-026",
    "application/use_cases/suspend_service.py": "TEN-026",
    "domain/rules/network_board.py": "TEN-057",
}


def _called_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _zone_missing_calls(path: Path) -> list[str]:
    found: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Call):
            continue
        name = _called_name(node)
        if name not in ZONE_POSITION:
            continue
        if any(keyword.arg == "zone" for keyword in node.keywords):
            continue
        unpacked = any(isinstance(arg, ast.Starred) for arg in node.args) or any(
            keyword.arg is None for keyword in node.keywords
        )
        if not unpacked and len(node.args) > ZONE_POSITION[name]:
            continue
        found.append(f"{name}:{node.lineno}")
    return found


def _offenders() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        calls = _zone_missing_calls(path)
        if calls:
            found[path.relative_to(SOURCE_ROOT).as_posix()] = calls
    return found


def test_every_caller_passes_its_zone_or_is_on_the_ratchet() -> None:
    offenders = _offenders()
    assert set(offenders) <= set(ZONE_NOT_YET_THREADED), offenders


def test_every_ratchet_entry_still_offends_and_names_its_task() -> None:
    offenders = _offenders()
    for relative, owner in ZONE_NOT_YET_THREADED.items():
        assert re.fullmatch(r"TEN-\d{3}", owner), (relative, owner)
        assert relative in offenders, f"{relative} passes its zone now: remove it"


def test_no_rule_module_reads_a_london_constant_for_a_tenant_decision() -> None:
    """The rule modules that take a zone use it: none of them names `LONDON`, `to_london` or
    `london_to_utc` any more (the zone-named helpers are the only way in)."""
    rules = SOURCE_ROOT / "domain" / "rules"
    for name in ("schedule.py", "opening_hours.py", "alerts.py", "freshness.py", "status.py"):
        text = (rules / name).read_text(encoding="utf-8")
        tree = ast.parse(text)
        names: set[Any] = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        names |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        assert not names & {"to_london", "london_to_utc"}, name
