"""Week summary for the COO and ICB (U35, docs/spec/domain-rules.md section 10).

Figures for one Monday-to-Sunday week in London time, converted to UTC (so a week that crosses the
clock change has 169 hours). Every count under 10 is hidden, and so is a percentage or a median
whose base is under 10: a small group must not be identifiable. Outcomes after referral are not
shown. "Time back" is an estimate and is labelled as one.

Reads only: no unit of work writes. The tenant comes from the unit of work (DEC-146); the summary
of a network is not built here (bookings and cases are not shared, DEC-132). Decisions:
docs/delivery/fragments/U35.md.
"""

import math
import statistics
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Final, Protocol

from diucs.application.actor import Actor
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.domain.codes import BestFitNotUsedReason, Outcome, ReportSource, Role
from diucs.domain.errors import NotAllowed, ValidationFailed
from diucs.domain.model.case import Case
from diucs.domain.model.tenant_policy import DEFAULT_POLICY, TenantPolicy
from diucs.domain.rules.london_time import london_to_utc
from diucs.domain.rules.schedule import reply_by

SMALL_GROUP: Final = 10
"""Counts, and bases of percentages and medians, below this are hidden (domain-rules 10)."""
_BEST_FIT_UNAVAILABLE_REASONS: Final = frozenset(
    {BestFitNotUsedReason.FULL, BestFitNotUsedReason.DECLINED, BestFitNotUsedReason.DATA_TOO_OLD}
)
_READERS: Final = frozenset({Role.EXEC, Role.LEAD})


@dataclass(frozen=True, slots=True)
class Measure:
    """One figure. A hidden figure carries no value: the caller shows that it is withheld."""

    value: float | int | None
    hidden: bool
    label: str


def london_week(week_start: date) -> tuple[datetime, datetime]:
    """The UTC instants of Monday 00:00 London and of the following Monday 00:00 London."""
    if week_start.weekday() != 0:
        raise ValueError("a week starts on a Monday")
    start = london_to_utc(week_start, time(0))
    end = london_to_utc(week_start + timedelta(days=7), time(0))
    return start, end


def count_measure(count: int, label: str) -> Measure:
    if count < SMALL_GROUP:
        return Measure(value=None, hidden=True, label=label)
    return Measure(value=count, hidden=False, label=label)


def percent_measure(part: int, base: int, label: str) -> Measure:
    """The share of base, rounded half up to a whole per cent. Hidden when the base is small."""
    if base < SMALL_GROUP:
        return Measure(value=None, hidden=True, label=label)
    return Measure(value=math.floor(100 * part / base + 0.5), hidden=False, label=label)


def median_measure(values: Sequence[float], label: str) -> Measure:
    if len(values) < SMALL_GROUP:
        return Measure(value=None, hidden=True, label=label)
    return Measure(value=statistics.median(values), hidden=False, label=label)


def on_time_updates(
    prompts: Sequence[tuple[str, datetime]],
    reports: Sequence[tuple[str, datetime]],
    policy: TenantPolicy = DEFAULT_POLICY,
) -> int:
    """Reports that arrive at or before the reply-by of the prompt they answer. A report answers
    the latest prompt of its service that was due at or before it; a report before any prompt of
    its service answers none. The reply-by is due plus the reply window (30 minutes, inclusive)."""
    dues: dict[str, list[datetime]] = defaultdict(list)
    for service_id, due in prompts:
        dues[service_id].append(due)
    for service_id in dues:
        dues[service_id].sort()
    on_time = 0
    for service_id, at in reports:
        answered = [due for due in dues.get(service_id, []) if due <= at]
        if answered and at <= reply_by(answered[-1], policy):
            on_time += 1
    return on_time


def time_back_text(updates: int, minutes_per_call: int | None) -> str:
    """The estimate of phone calls avoided. Below the small-group line the count is not stated; an
    unset minutes-per-call is shown as [x], never guessed."""
    if updates < SMALL_GROUP:
        counted = "Fewer than 10 updates by text, app or email"
    else:
        counted = f"{updates} updates by text, app or email"
    minutes = "[x]" if minutes_per_call is None else str(minutes_per_call)
    return f"{counted}. Each replaces about one phone call of {minutes} minutes. Estimate."


def check_may_read(actor: Actor) -> None:
    if actor.role not in _READERS:
        raise NotAllowed("only the exec and the lead may read the week summary")


def _best_fit_unavailable(case: Case) -> bool:
    return case.outcome is Outcome.NO_SERVICE_FITS or case.best_fit_not_used in (
        _BEST_FIT_UNAVAILABLE_REASONS
    )


class WeekSummarySettings(Protocol):
    minutes_per_avoided_call: int | None


@dataclass(frozen=True, slots=True)
class GetWeekSummaryCommand:
    actor: Actor
    week_start: date


@dataclass(frozen=True, slots=True)
class WeekSummary:
    week_start: date
    referrals: Measure
    best_fit_unavailable_pct: Measure
    on_time_pct: Measure
    median_minutes_to_confirmed: Measure
    updates_by_channel: dict[str, Measure]
    time_back_text: str


class GetWeekSummary:
    def __init__(
        self, uow_factory: UnitOfWorkFactory, settings: WeekSummarySettings, clock: Clock
    ) -> None:
        self._uow_factory = uow_factory
        self._settings = settings
        self._clock = clock

    async def execute(self, command: GetWeekSummaryCommand) -> WeekSummary:
        check_may_read(command.actor)
        if command.week_start.weekday() != 0:
            raise ValidationFailed("week_start", "must be a Monday")
        start, end = london_week(command.week_start)
        async with self._uow_factory() as uow:
            cases = await uow.cases.opened_between(start, end)
            reports = await uow.capacity.reports_between(start, end)
            bookings = await uow.bookings.confirmed_between(start, end)
            prompts = await uow.communications.prompts_due_between(start, end)

        unavailable = sum(1 for case in cases if _best_fit_unavailable(case))
        minutes = [
            (booking.confirmed_at - booking.requested_at).total_seconds() / 60
            for booking in bookings
            if booking.confirmed_at is not None and start <= booking.confirmed_at < end
        ]
        counts = {"text": 0, "app": 0, "email/link": 0}
        for report in reports:
            if report.source is ReportSource.TEXT:
                counts["text"] += 1
            elif report.source is ReportSource.APP:
                counts["app"] += 1
            elif report.source in (ReportSource.EMAIL, ReportSource.LINK):
                counts["email/link"] += 1
        updates = sum(counts.values())
        on_time = on_time_updates(
            [(prompt.service_id, prompt.due_at) for prompt in prompts],
            [(report.service_id, report.effective_at) for report in reports],
        )
        return WeekSummary(
            week_start=command.week_start,
            referrals=count_measure(len(cases), "referrals"),
            best_fit_unavailable_pct=percent_measure(
                unavailable, len(cases), "best fit not available"
            ),
            on_time_pct=percent_measure(on_time, len(prompts), "capacity updates on time"),
            median_minutes_to_confirmed=median_measure(minutes, "median minutes to confirmed"),
            updates_by_channel={
                channel: count_measure(count, channel) for channel, count in counts.items()
            },
            time_back_text=time_back_text(updates, self._settings.minutes_per_avoided_call),
        )
