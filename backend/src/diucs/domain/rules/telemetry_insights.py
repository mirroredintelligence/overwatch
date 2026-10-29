"""Telemetry aggregates: the funnels, the suppression floor and the friction rate (O08).

Pure rules, no I/O. Thresholds are named constants; the two marked [ASSUMED] are starting values
from docs/spec/observability.md ("Funnels by role", "Rolling friction into a score", "Privacy
and governance").

Each funnel is a fixed list of steps (observability.md). A step is defined by one UI or domain
event, so it has one meaning everywhere. The event names below are the names the telemetry and
the domain use for that step; a step whose event is not yet emitted counts zero until it is (no
fabricated numbers). Branches (an expired booking, a call that is phoned) are steps too, but
they are not in the order of the funnel: `branch=True`.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median
from types import MappingProxyType
from typing import Final

from diucs.domain.model.telemetry_aggregates import (
    ElementUsageDailyRow,
    FrictionDailyRow,
    FunnelDailyRow,
    QueryStatDailyRow,
    RouteDailyRow,
)

# Groups under this many sessions are not reported as numbers (observability.md, "Privacy and
# governance").
SUPPRESS_BELOW_SESSIONS: Final = 10
# An element whose friction rate is over this share is listed for review [ASSUMED].
FRICTION_REVIEW_RATE: Final = 0.05
# The friction rate is taken over this many days, the end day included (observability.md, 7 days).
RATE_WINDOW_DAYS: Final = 7


@dataclass(frozen=True, slots=True)
class FunnelStep:
    step: str
    event: str
    branch: bool = False


def _steps(*rows: tuple[str, str] | tuple[str, str, bool]) -> tuple[FunnelStep, ...]:
    return tuple(FunnelStep(*row) for row in rows)


# The seven funnels, keyed by a stable id. Each value is the steps in order, with the branches last.
FUNNELS: Mapping[str, tuple[FunnelStep, ...]] = MappingProxyType(
    {
        "reporter-set-up": _steps(
            ("Invitation delivered", "comms.invitation_delivered"),
            ("Link opened", "ui.page_view"),
            ("Welcome started", "ui.click"),
            ("Code requested", "reporter.code_requested"),
            ("Code verified", "reporter.code_verified"),
            ("Channel chosen", "ui.chip"),
            ("Home-screen guide viewed", "ui.page_view"),
            ("Opened from home screen", "app.opened"),
            ("Notification prompt shown", "push.prompt_shown"),
            ("Notifications allowed", "push.allowed"),
            ("PIN created", "reporter.pin_created"),
            ("PIN confirmed", "reporter.pin_confirmed"),
            ("First prompt answered", "domain.prompt_answered"),
        ),
        "daily-capacity-loop": _steps(
            ("Prompt sent", "comms.prompt_sent"),
            ("Delivered", "comms.prompt_delivered"),
            ("Opened", "comms.prompt_opened"),
            ("Responded", "domain.reply_received"),
            ("Recorded", "domain.capacity_recorded"),
            ("Echo delivered", "comms.echo_delivered"),
        ),
        "booking-service-side": _steps(
            ("Request sent", "comms.booking_request_sent"),
            ("Delivered", "comms.booking_request_delivered"),
            ("Opened", "comms.booking_request_opened"),
            ("Decision made", "domain.booking_decided"),
            ("Echo delivered", "comms.booking_echo_delivered"),
            ("Expired", "domain.booking_expired", True),
        ),
        "advisor-call": _steps(
            ("Case opened", "domain.case_opened"),
            ("Needs captured", "ui.submit"),
            ("Options viewed", "ui.page_view"),
            ("Criteria viewed", "ui.page_view"),
            ("Request sent", "domain.booking_requested"),
            ("Confirmed", "domain.booking_confirmed"),
            ("Outcome recorded", "domain.outcome_recorded"),
            ("Summary copied", "ui.click"),
            ("Case closed", "domain.case_closed"),
            ("Phoned", "domain.advisor_phoned", True),
            ("Clinical advice requested", "domain.clinical_advice_requested", True),
            ("No service fits", "domain.no_service_fits", True),
        ),
        "registration": _steps(
            ("Invited", "registration.invited"),
            ("Started", "registration.started"),
            ("Organisation done", "registration.organisation_done"),
            ("Location done", "registration.location_done"),
            ("Service done", "registration.service_done"),
            ("Capacity reporting done", "registration.capacity_done"),
            ("Submitted", "registration.submitted"),
            ("Checks complete", "registration.checks_complete"),
            ("Approved", "registration.approved"),
            ("Test answered", "registration.test_answered"),
            ("Live", "registration.live"),
        ),
        "criteria-review": _steps(
            ("Reminder sent", "criteria.reminder_sent"),
            ("Opened", "criteria.opened"),
            ("Confirmed or changed", "criteria.confirmed_or_changed"),
            ("Submitted", "criteria.submitted"),
            ("Second approval", "criteria.second_approval"),
            ("Current", "criteria.current"),
        ),
        "coo-icb-adoption": _steps(
            ("Invited", "adoption.invited"),
            ("Set up", "adoption.set_up"),
            ("Alerts chosen", "adoption.alerts_chosen"),
            ("First alert received", "adoption.first_alert_received"),
            ("First acknowledged", "adoption.first_acknowledged"),
            ("Weekly use", "adoption.weekly_use"),
        ),
    }
)


def is_suppressed(sessions: int) -> bool:
    """True when a group is too small to report: fewer than SUPPRESS_BELOW_SESSIONS sessions."""
    return sessions < SUPPRESS_BELOW_SESSIONS


def friction_rate(events: int, interactions: int) -> float | None:
    """Friction events divided by interactions, or None when there were no interactions."""
    if interactions <= 0:
        return None
    return events / interactions


def for_review(events: int, interactions: int) -> bool:
    """True when the rate is strictly over FRICTION_REVIEW_RATE. Exactly on the line is not
    over it.

    """
    rate = friction_rate(events, interactions)
    return rate is not None and rate > FRICTION_REVIEW_RATE


def rate_window_start(end: date) -> date:
    """The first day of the friction window that ends on `end` (the end day is one of the seven)."""
    return end - timedelta(days=RATE_WINDOW_DAYS - 1)


# The read side (stub for the red commit): figures from the stored rows, suppression applied.


@dataclass(frozen=True, slots=True)
class FunnelFigure:
    step: str
    branch: bool
    role: str
    channel: str
    device: str
    entered: int | None
    completed: int | None
    conversion: float | None
    median_ms: float | None
    suppressed: bool


@dataclass(frozen=True, slots=True)
class FrictionFigure:
    element_id: str
    role: str
    device: str
    events: int | None
    interactions: int | None
    rate: float | None
    for_review: bool
    suppressed: bool


@dataclass(frozen=True, slots=True)
class RouteFigure:
    route: str
    role: str
    device: str
    p50: float | None
    p75: float | None
    p95: float | None
    lcp75: float | None
    inp75: float | None
    cls75: float | None
    errors: int | None
    suppressed: bool


@dataclass(frozen=True, slots=True)
class QueryFigure:
    query_id: str
    calls: int
    p50: float | None
    p95: float | None
    errors: int


def _step_position(funnel: str, step: str) -> int:
    for position, candidate in enumerate(FUNNELS.get(funnel, ())):
        if candidate.step == step:
            return position
    return len(FUNNELS.get(funnel, ()))


def funnel_figures(rows: Sequence[FunnelDailyRow]) -> list[FunnelFigure]:
    """One figure per step, role, channel, device and branch, summed over the rows given. A group
    whose
    entered count is under the floor has no numbers: the figure says it is suppressed.

    """
    totals: dict[tuple[str, str, str, str, str, bool], list[float]] = {}
    medians: dict[tuple[str, str, str, str, str, bool], list[float]] = {}
    for row in rows:
        key = (row.funnel, row.step, row.role, row.channel, row.device, row.branch)
        totals.setdefault(key, [0, 0])
        totals[key][0] += row.entered
        totals[key][1] += row.completed
        if row.median_ms is not None:
            medians.setdefault(key, []).append(row.median_ms)
    figures: list[FunnelFigure] = []
    for key in sorted(totals, key=lambda k: (k[0], _step_position(k[0], k[1]), k[2], k[3], k[4])):
        funnel, step, role, channel, device, branch = key
        entered, completed = int(totals[key][0]), int(totals[key][1])
        suppressed = is_suppressed(entered)
        figures.append(
            FunnelFigure(
                step=step,
                branch=branch,
                role=role,
                channel=channel,
                device=device,
                entered=None if suppressed else entered,
                completed=None if suppressed else completed,
                conversion=None if suppressed or entered == 0 else completed / entered,
                median_ms=None if suppressed or key not in medians else median(medians[key]),
                suppressed=suppressed,
            )
        )
    return figures


def friction_figures(
    friction: Sequence[FrictionDailyRow], usage: Sequence[ElementUsageDailyRow]
) -> list[FrictionFigure]:
    """Friction per element, role and device: the events of every kind over the interactions, with
    the
    review flag. The sessions behind a group are the sum of its daily session counts (a session that
    spans two days is counted twice, which only makes the floor easier to pass; see the decision).

    """
    events: dict[tuple[str, str, str], int] = {}
    for row in friction:
        key = (row.element_id, row.role, row.device)
        events[key] = events.get(key, 0) + row.events
    interactions: dict[tuple[str, str, str], int] = {}
    sessions: dict[tuple[str, str, str], int] = {}
    for usage_row in usage:
        key = (usage_row.element_id, usage_row.role, usage_row.device)
        interactions[key] = interactions.get(key, 0) + usage_row.interactions
        sessions[key] = sessions.get(key, 0) + usage_row.sessions
    figures: list[FrictionFigure] = []
    for key in sorted(set(events) | set(interactions)):
        element_id, role, device = key
        group_sessions = sessions.get(key, 0)
        if is_suppressed(group_sessions):
            figures.append(FrictionFigure(element_id, role, device, None, None, None, False, True))
            continue
        count, seen = events.get(key, 0), interactions.get(key, 0)
        figures.append(
            FrictionFigure(
                element_id=element_id,
                role=role,
                device=device,
                events=count,
                interactions=seen,
                rate=friction_rate(count, seen),
                for_review=for_review(count, seen),
                suppressed=False,
            )
        )
    return figures


def route_figures(rows: Sequence[RouteDailyRow]) -> list[RouteFigure]:
    """One figure per route row. A row under the floor shows no timing and no error count."""
    figures: list[RouteFigure] = []
    for row in rows:
        suppressed = is_suppressed(row.sessions)
        figures.append(
            RouteFigure(
                route=row.route,
                role=row.role,
                device=row.device,
                p50=None if suppressed else row.p50,
                p75=None if suppressed else row.p75,
                p95=None if suppressed else row.p95,
                lcp75=None if suppressed else row.lcp75,
                inp75=None if suppressed else row.inp75,
                cls75=None if suppressed else row.cls75,
                errors=None if suppressed else row.errors,
                suppressed=suppressed,
            )
        )
    return figures


def query_figures(rows: Sequence[QueryStatDailyRow]) -> list[QueryFigure]:
    """One figure per query and day. Query statistics name a query by its registered id only."""
    return [
        QueryFigure(
            query_id=row.query_id,
            calls=row.calls,
            p50=row.p50,
            p95=row.p95,
            errors=row.errors,
        )
        for row in rows
    ]
