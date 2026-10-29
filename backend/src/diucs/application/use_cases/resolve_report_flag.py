"""Resolve report flags for the shift lead (U39).

A report flag says a capacity report needs a check by phone (U07). The lead lists the open flags,
each with a short description built from the reports, and resolves each one: checked (looked at, no
action), accepted (the figure stands) or phoned (the lead phoned the service; the figure they were
told is recorded as a new advisor-phoned report). A resolved flag keeps its outcome, the lead who
resolved it and the time, and it is never resolved twice. The capacity report is never edited.

Decisions: docs/delivery/fragments/U39.md. RecordAdvisorPhoned (U13) is not built yet, so a phoned
outcome records its figure through ReportCapacity with source advisor-phoned, which is the path
U13 will also take.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final, Literal

from diucs.application.actor import Actor
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.report_capacity import ReportCapacity, ReportCapacityCommand
from diucs.application.use_cases.report_flags import LOOKBACK
from diucs.domain.codes import ReportFlagReason, ReportSource, ReportType, Role
from diucs.domain.errors import Conflict, InvalidTransition, NotAllowed, NotFound, ValidationFailed
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.flags import (
    REPORT_FLAG_ACCEPTED,
    REPORT_FLAG_CHECKED,
    REPORT_FLAG_OPEN,
    ReportFlag,
)
from diucs.domain.rules.london_time import format_hhmm
from diucs.domain.rules.report_flags import MANY_CHANGES_WINDOW

AUDIT_ACTION: Final = "U"
MAX_FIGURE: Final = 999
_STATUS_OF_OUTCOME: Final[dict[str, str]] = {
    "checked": REPORT_FLAG_CHECKED,
    "accepted": REPORT_FLAG_ACCEPTED,
    "phoned": REPORT_FLAG_CHECKED,
}
_SOURCE_WORDS: Final[dict[ReportSource, str]] = {
    ReportSource.TEXT: "text",
    ReportSource.APP: "app",
    ReportSource.LINK: "link",
    ReportSource.EMAIL: "email",
    ReportSource.ADVISOR_PHONED: "phone",
    ReportSource.FEED: "feed",
}


def check_lead(actor: Actor) -> None:
    if actor.role is not Role.LEAD:
        raise NotAllowed("only the shift lead may resolve report flags")


def resolved_status(outcome: str) -> str:
    """The flag status an outcome leaves the flag in. An unknown outcome is refused."""
    if not isinstance(outcome, str) or outcome not in _STATUS_OF_OUTCOME:
        raise ValidationFailed("outcome", "must be checked, accepted or phoned")
    return _STATUS_OF_OUTCOME[outcome]


def check_resolution(outcome: str, phoned_value: int | None) -> None:
    """The outcome is one of the three, and a figure is given exactly when the outcome is phoned."""
    resolved_status(outcome)
    if outcome == "phoned":
        if type(phoned_value) is not int or not 0 <= phoned_value <= MAX_FIGURE:
            raise ValidationFailed("phoned_value", "must be a whole number from 0 to 999")
    elif phoned_value is not None:
        raise ValidationFailed("phoned_value", "is given only when the outcome is phoned")


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"


def sequence_of(reports: Sequence[CapacityReport]) -> str:
    """The figures of reports in order, a confirmation written as Y. A leading run of Y is written
    as "All Y"; every later item follows "then": "All Y, then 9, then 2"."""
    items = ["Y" if r.report_type is ReportType.CONFIRMED else str(r.value) for r in reports]
    if not items:
        return ""
    if items[0] == "Y":
        run = 0
        while run < len(items) and items[run] == "Y":
            run += 1
        parts = ["All Y"]
        rest = items[run:]
    else:
        parts = [items[0]]
        rest = items[1:]
    parts.extend(f"then {item}" for item in rest)
    return ", ".join(parts)


def _source_words(reports: Sequence[CapacityReport]) -> str:
    words: list[str] = []
    for report in reports:
        word = _SOURCE_WORDS[report.source]
        if word not in words:
            words.append(word)
    return " and ".join(words)


def _out_of_range(
    service_name: str,
    usual_range: tuple[int, int],
    report: CapacityReport,
    window: Sequence[CapacityReport],
) -> str:
    upto = sorted(
        (r for r in window if r.effective_at <= report.effective_at), key=lambda r: r.effective_at
    )
    pair = upto[-2:] if len(upto) >= 2 else [report]
    values = [r.value for r in pair]
    if len(pair) == 2 and values[0] == values[1]:
        head = f"{service_name} reported {values[0]}, twice."
    else:
        head = f"{service_name} reported " + ", then ".join(str(v) for v in values) + "."
    low, high = usual_range
    times = " and ".join(format_hhmm(r.effective_at) for r in pair)
    return f"{head} Usual range {low} to {high}. Sent {times} by {_source_words(pair)}."


def _many_changes(
    service_name: str, report: CapacityReport, window: Sequence[CapacityReport]
) -> str:
    span = sorted(
        (
            r
            for r in window
            if report.effective_at - MANY_CHANGES_WINDOW <= r.effective_at <= report.effective_at
        ),
        key=lambda r: r.effective_at,
    )
    first, last = span[0].effective_at, span[-1].effective_at
    minutes = max(1, math.ceil((last - first).total_seconds() / 60))
    return (
        f"{service_name}: {_count(len(span), 'report')} in {_count(minutes, 'minute')}. "
        f"{sequence_of(span)}."
    )


def _differs_from_phoned(
    service_name: str, report: CapacityReport, window: Sequence[CapacityReport]
) -> str:
    told = [
        r
        for r in window
        if r.source is ReportSource.ADVISOR_PHONED and r.effective_at <= report.effective_at
    ]
    given = f"{service_name} reported {report.value} by {_source_words([report])}"
    if not told:
        return f"{given}, which differs from the figure the advisor phoned."
    phoned = max(told, key=lambda r: r.effective_at)
    return f"{given}, but the advisor phoned {phoned.value} at {format_hhmm(phoned.effective_at)}."


def describe_flag(
    flag: ReportFlag,
    *,
    service_name: str,
    usual_range: tuple[int, int],
    report: CapacityReport,
    window: Sequence[CapacityReport],
) -> str:
    """The short description the list shows, from the flagged report and the reports around it
    (the same service, in the rules' look-back window). Times are London times."""
    if flag.reason is ReportFlagReason.OUT_OF_RANGE_TWICE:
        return _out_of_range(service_name, usual_range, report, window)
    if flag.reason is ReportFlagReason.MANY_CHANGES:
        return _many_changes(service_name, report, window)
    if flag.reason is ReportFlagReason.DIFFERS_FROM_PHONED:
        return _differs_from_phoned(service_name, report, window)
    raise ValidationFailed("reason", "is not a report flag reason")


@dataclass(frozen=True, slots=True)
class ReportFlagView:
    flag_id: str
    service_id: str
    service_name: str
    reason: ReportFlagReason
    description: str
    raised_at: datetime


@dataclass(frozen=True, slots=True)
class ResolveReportFlagCommand:
    idempotency_key: str
    actor: Actor
    flag_id: str
    outcome: Literal["checked", "accepted", "phoned"]
    phoned_value: int | None = None


@dataclass(frozen=True, slots=True)
class ResolveReportFlagResult:
    flag_id: str
    status: str
    outcome: str
    phoned_report_id: str | None = None


@dataclass(frozen=True, slots=True)
class ListReportFlagsQuery:
    actor: Actor


class ListReportFlags:
    """The open report flags, newest first, each with its description (the shift lead's list)."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def execute(self, query: ListReportFlagsQuery) -> list[ReportFlagView]:
        check_lead(query.actor)
        views: list[ReportFlagView] = []
        async with self._uow_factory() as uow:
            for flag in await uow.flags.open_report_flags():
                profile = await uow.services.get(flag.service_id)
                report = await uow.capacity.get(flag.report_id)
                if profile is None or report is None:
                    raise NotFound("a flag refers to a service or report that is not stored")
                window = await uow.capacity.reports_since(
                    flag.service_id, flag.created_at - LOOKBACK
                )
                views.append(
                    ReportFlagView(
                        flag_id=flag.id,
                        service_id=flag.service_id,
                        service_name=profile.name,
                        reason=flag.reason,
                        description=describe_flag(
                            flag,
                            service_name=profile.name,
                            usual_range=profile.usual_range,
                            report=report,
                            window=window,
                        ),
                        raised_at=flag.created_at,
                    )
                )
        views.sort(key=lambda view: (view.raised_at, view.flag_id), reverse=True)
        return views


class ResolveReportFlag:
    """Resolve one open flag. A phoned outcome first records the figure as an advisor-phoned report
    through ReportCapacity, in its own unit of work with a key derived from the command's, so a
    retry replays it; then the flag is resolved in a unit of work of its own, under the service's
    lock. The report is never edited."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        report_capacity: ReportCapacity,
        clock: Clock,
    ) -> None:
        self._uow_factory = uow_factory
        self._report_capacity = report_capacity
        self._clock = clock

    async def execute(self, command: ResolveReportFlagCommand) -> ResolveReportFlagResult:
        check_lead(command.actor)
        check_resolution(command.outcome, command.phoned_value)
        status = resolved_status(command.outcome)
        async with self._uow_factory() as uow:
            seen = await uow.flags.report_flag(command.flag_id)
        if seen is None:
            raise NotFound("no report flag with this id")
        if seen.status != REPORT_FLAG_OPEN:
            raise Conflict("this flag is already resolved")

        phoned_report_id: str | None = None
        if command.outcome == "phoned":
            recorded = await self._report_capacity.execute(
                ReportCapacityCommand(
                    idempotency_key=f"{command.idempotency_key}:phoned",
                    actor=command.actor,
                    service_id=seen.service_id,
                    value=command.phoned_value or 0,
                    source=ReportSource.ADVISOR_PHONED,
                    send_echo=False,
                )
            )
            phoned_report_id = recorded.report_id

        now = self._clock.now()
        async with self._uow_factory() as uow:
            await uow.capacity.lock_service(seen.service_id)
            current = await uow.flags.report_flag(command.flag_id)
            if current is None:
                raise NotFound("no report flag with this id")
            if current.status != REPORT_FLAG_OPEN:
                raise Conflict("this flag is already resolved")
            resolved = replace(
                current,
                status=status,
                resolved_at=now,
                outcome=command.outcome,
                resolved_by=command.actor.practitioner_id,
            )
            try:
                await uow.flags.save_report_flag(resolved)
            except InvalidTransition as error:
                raise Conflict("this flag is already resolved") from error
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_ACTION,
                    use_case="ResolveReportFlag",
                    actor=command.actor,
                    entity_ids=(current.id, current.report_id, current.service_id),
                    snapshot={"outcome": command.outcome, "status": status},
                    at=now,
                )
            )
            await uow.commit()
        return ResolveReportFlagResult(
            flag_id=current.id,
            status=status,
            outcome=command.outcome,
            phoned_report_id=phoned_report_id,
        )
