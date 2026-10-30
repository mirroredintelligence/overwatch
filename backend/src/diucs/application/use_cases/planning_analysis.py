"""Planning analysis from decision snapshots (U43).

From the closed cases of a period, the decision each one was made on (the last FilterOptions display
before its outcome), and the declines recorded in the period, it shows where capacity ran out and
where patients went instead. Counts under MIN_COUNT (10) are hidden, and so is a share whose base
is under 10. Only aggregates leave the tenant: no case id, reference, postcode or patient value is
returned (DEC-393).

Cohort (DEC-393): age 65-79 or 80+, urgency within 2 hrs, referrer ambulance crew or care home, and
(for a need group) a need in that group. Best fit: the first option in the display's snapshot
[ASSUMED, DEC-393]; the snapshot keeps board order, not travel order, so this is the first option
listed, which may not be the nearest. Best fit unavailable: its status is not-accepting,
over-capacity or not-updated, or its number is 0.

Pure: no I/O and no clock. Times are aware instants; weekdays and bands are London wall-clock.
"""

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final

from diucs.application.actor import Actor
from diucs.application.ports.outbound.audit import AuditEntry, AuditRecord
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.domain.codes import Role
from diucs.domain.errors import NotAllowed, ValidationFailed
from diucs.domain.rules.london_time import to_london

MIN_COUNT: Final = 10
ALLOWED_ROLES: Final = frozenset({Role.LEAD, Role.EXEC})
PLANNING_USE_CASE: Final = "PlanningAnalysis"
READ_ACTION: Final = "R"
OUTCOME_USE_CASE: Final = "RecordOutcome"
DECLINE_USE_CASE: Final = "RecordDecline"
OPEN_USE_CASE: Final = "OpenCase"
DISPLAY_USE_CASE: Final = "FilterOptions"
ALLOWED_PERIODS: Final = (30, 90, 365)
NEED_GROUPS: Final[Mapping[str, frozenset[str] | None]] = {
    "all": None,
    "falls-and-frailty": frozenset({"fall-no-injury", "frailty"}),
    "iv-therapy": frozenset({"iv-therapy"}),
    "palliative": frozenset({"palliative"}),
}
COHORT_AGE_BANDS: Final = frozenset({"65-79", "80+"})
COHORT_REFERRERS: Final = frozenset({"ambulance-crew", "care-home"})
COHORT_URGENCY: Final = "within-2-hrs"
UNAVAILABLE_STATUSES: Final = frozenset({"not-accepting", "over-capacity", "not-updated"})
SHOWN_AS_OPTION: Final = "option"
NO_DESTINATION: Final = "no destination recorded"
BANDS: Final = ((0, 6, "00-06"), (6, 12, "06-12"), (12, 18, "12-18"), (18, 24, "18-24"))


@dataclass(frozen=True, slots=True)
class PlanningQuery:
    period_days: int
    need_group: str


@dataclass(frozen=True, slots=True)
class HiddenCount:
    value: int | None
    hidden: bool


@dataclass(frozen=True, slots=True)
class OutcomeFact:
    case_key: str
    opened_at: datetime
    closed_at: datetime
    age_band: str | None
    urgency: str | None
    referrer: str | None
    needs: tuple[str, ...]
    destination_id: str | None


@dataclass(frozen=True, slots=True)
class DisplayFact:
    case_key: str
    at: datetime
    rows: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True, slots=True)
class DeclineFact:
    service_id: str
    at: datetime


@dataclass(frozen=True, slots=True)
class FlowRow:
    best_fit: str
    state: str
    destination: str
    count: HiddenCount


@dataclass(frozen=True, slots=True)
class PlanningResult:
    referrals: HiddenCount
    best_fit_unavailable: HiddenCount
    best_fit_unavailable_pct: HiddenCount
    went_elsewhere: HiddenCount
    flows: tuple[FlowRow, ...]
    heat: dict[tuple[int, str], HiddenCount]
    busiest: tuple[int, str] | None
    declined_despite: tuple[tuple[str, HiddenCount], ...]


def validate_query(query: PlanningQuery) -> None:
    if query.period_days not in ALLOWED_PERIODS:
        raise ValidationFailed("period_days", "must be 30, 90 or 365")
    if query.need_group not in NEED_GROUPS:
        raise ValidationFailed("need_group", "is not a known need group")


def in_cohort(fact: OutcomeFact, need_group: str) -> bool:
    """The default cohort, and the need group when one is given (DEC-393)."""
    if fact.age_band not in COHORT_AGE_BANDS:
        return False
    if fact.urgency != COHORT_URGENCY:
        return False
    if fact.referrer not in COHORT_REFERRERS:
        return False
    group = NEED_GROUPS.get(need_group)
    return group is None or bool(group.intersection(fact.needs))


def decision_for(fact: OutcomeFact, displays: Sequence[DisplayFact]) -> DisplayFact | None:
    """The last display of this case at or before its outcome: the one the decision was made on."""
    chosen: DisplayFact | None = None
    for display in displays:
        if display.case_key != fact.case_key or display.at > fact.closed_at:
            continue
        if chosen is None or display.at >= chosen.at:
            chosen = display
    return chosen


def best_fit(rows: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    for row in rows:
        if row.get("shown_as") == SHOWN_AS_OPTION:
            return row
    return None


def is_unavailable(row: Mapping[str, Any]) -> bool:
    return row["status"] in UNAVAILABLE_STATUSES or row["number"] == 0


def _state(row: Mapping[str, Any]) -> str:
    if row["status"] == "not-accepting":
        return "not accepting"
    if row["status"] == "not-updated":
        return "not updated"
    return "full"


def hide(count: int) -> HiddenCount:
    if count < MIN_COUNT:
        return HiddenCount(None, True)
    return HiddenCount(count, False)


def share_of(part: int, base: int) -> HiddenCount:
    """A whole-percent share; hidden when its base is under MIN_COUNT (half rounds up)."""
    if base < MIN_COUNT:
        return HiddenCount(None, True)
    return HiddenCount(math.floor(part * 100 / base + 0.5), False)


def heat_cell(opened_at: datetime) -> tuple[int, str]:
    """The London weekday (Monday is 0) and six-hour band of a case's arrival."""
    local = to_london(opened_at)
    for start, end, label in BANDS:
        if start <= local.hour < end:
            return local.weekday(), label
    raise ValueError("no band for an hour of the day")


def build_planning(
    query: PlanningQuery,
    outcomes: Sequence[OutcomeFact],
    displays: Sequence[DisplayFact],
    declines: Sequence[DeclineFact],
    names: Mapping[str, str],
) -> PlanningResult:
    validate_query(query)

    referrals = 0
    unavailable = 0
    elsewhere = 0
    flows: Counter[tuple[str, str, str]] = Counter()
    heat: Counter[tuple[int, str]] = Counter()

    by_case: dict[str, list[DisplayFact]] = {}
    for display in displays:
        by_case.setdefault(display.case_key, []).append(display)

    for fact in outcomes:
        if not in_cohort(fact, query.need_group):
            continue
        decision = decision_for(fact, by_case.get(fact.case_key, []))
        if decision is None:
            continue
        referrals += 1
        top = best_fit(decision.rows)
        if top is None or not is_unavailable(top):
            continue
        unavailable += 1
        destination = fact.destination_id
        option_ids = {row["id"] for row in decision.rows if row.get("shown_as") == SHOWN_AS_OPTION}
        if destination is not None and destination in option_ids and destination != top["id"]:
            elsewhere += 1
        destination_name = (
            NO_DESTINATION if destination is None else names.get(destination, destination)
        )
        flows[(names.get(top["id"], top["id"]), _state(top), destination_name)] += 1
        heat[heat_cell(fact.opened_at)] += 1

    busiest: tuple[int, str] | None = None
    if heat:
        best_cell, best_count = min(heat.items(), key=lambda item: (-item[1], item[0]))
        if best_count >= MIN_COUNT:
            busiest = best_cell

    declined: Counter[str] = Counter()
    for decline in declines:
        declined[names.get(decline.service_id, decline.service_id)] += 1

    return PlanningResult(
        referrals=hide(referrals),
        best_fit_unavailable=hide(unavailable),
        best_fit_unavailable_pct=share_of(unavailable, referrals),
        went_elsewhere=hide(elsewhere),
        flows=tuple(
            FlowRow(best, state, destination, hide(count))
            for (best, state, destination), count in sorted(
                flows.items(), key=lambda item: (-item[1], item[0])
            )
        ),
        heat={cell: hide(count) for cell, count in sorted(heat.items())},
        busiest=busiest,
        declined_despite=tuple(
            (name, hide(count))
            for name, count in sorted(declined.items(), key=lambda item: (-item[1], item[0]))
        ),
    )


@dataclass(frozen=True, slots=True)
class RunPlanningCommand:
    actor: Actor
    query: PlanningQuery


def _instant(text: object) -> datetime:
    return datetime.fromisoformat(str(text))


def _outcome_fact(record: AuditRecord, referrer: str | None) -> OutcomeFact:
    snapshot = record.entry.snapshot or {}
    destination = snapshot.get("destination_service_id")
    return OutcomeFact(
        case_key=record.entry.entity_ids[0],
        opened_at=_instant(snapshot["opened_at"]),
        closed_at=record.entry.at,
        age_band=snapshot.get("age_band"),
        urgency=snapshot.get("urgency"),
        referrer=referrer,
        needs=tuple(snapshot.get("needs") or ()),
        destination_id=None if destination is None else str(destination),
    )


class RunPlanningAnalysis:
    """The planning analysis for the bound tenant. Reads only, and writes one audit entry for the
    query itself (its parameters, not its results). Lead and exec only (DEC-393)."""

    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, command: RunPlanningCommand) -> PlanningResult:
        if command.actor.role not in ALLOWED_ROLES:
            raise NotAllowed("only a shift lead or an executive may run the planning analysis")
        validate_query(command.query)
        now = self._clock.now()
        start = now - timedelta(days=command.query.period_days)
        async with self._uow_factory() as uow:
            window = await uow.audit.records_between(
                start, now, frozenset({OUTCOME_USE_CASE, DECLINE_USE_CASE})
            )
            outcome_records = [r for r in window if r.entry.use_case == OUTCOME_USE_CASE]
            decline_records = [r for r in window if r.entry.use_case == DECLINE_USE_CASE]
            case_ids = list(dict.fromkeys(r.entry.entity_ids[0] for r in outcome_records))
            opened = await uow.audit.records_for_many(case_ids, OPEN_USE_CASE)
            referrers = {
                r.entry.entity_ids[0]: (r.entry.snapshot or {}).get("referrer_type") for r in opened
            }
            shown = await uow.audit.records_for_many(case_ids, DISPLAY_USE_CASE)

            outcomes = [
                _outcome_fact(r, _text_or_none(referrers.get(r.entry.entity_ids[0])))
                for r in outcome_records
            ]
            displays = [
                DisplayFact(
                    case_key=r.entry.entity_ids[0],
                    at=r.entry.at,
                    rows=tuple((r.entry.snapshot or {}).get("services", [])),
                )
                for r in shown
            ]
            declines = [
                DeclineFact(service_id=str((r.entry.snapshot or {})["service_id"]), at=r.entry.at)
                for r in decline_records
            ]
            names: dict[str, str] = {}
            ids = {row["id"] for d in displays for row in d.rows}
            ids |= {d.service_id for d in declines}
            ids |= {f.destination_id for f in outcomes if f.destination_id is not None}
            for service_id in sorted(ids):
                profile = await uow.services.get(service_id)
                if profile is not None:
                    names[service_id] = profile.name

            result = build_planning(command.query, outcomes, displays, declines, names)
            await uow.audit.append(
                AuditEntry(
                    action=READ_ACTION,
                    use_case=PLANNING_USE_CASE,
                    actor=command.actor,
                    entity_ids=(),
                    snapshot={
                        "period_days": command.query.period_days,
                        "need_group": command.query.need_group,
                    },
                    at=now,
                )
            )
            await uow.commit()
        return result


def _text_or_none(value: object) -> str | None:
    return None if value is None else str(value)
