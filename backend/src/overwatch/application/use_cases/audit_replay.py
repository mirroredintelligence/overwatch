"""Audit replay of what the advisor saw (U42).

For one case, the replay shows the options the advisor was shown (the snapshot of the last
FilterOptions display before the first booking request, or the last display when nothing was
requested), and the timeline of the case's audit records and those of its bookings, in time order.
Opening the replay is itself an audit entry (use_case AuditReplay, action R), so who looked is
recorded. The chain is verified and reported as chain_ok.

Roles: lead and audit only (DEC-390). Read-only apart from the replay's own audit entry. The
snapshot of a display holds ids, status, number, data age and criteria version; it holds no
postcode, no district and no needs, and the replay adds none. Service names are the names the
advisor saw, kept in the snapshot (KI-474, DEC-1177); a display written before that shows the
current name and says so. The figure is what the service could take, "+n" for how far over capacity
it was, and none for a service that offered none: never the used count (H-190, KI-475). The options
are in the order they were shown, nearest first (H-193).

Decisions: DEC-390 (roles, the chosen display, the timeline), DEC-391 (names, the over-capacity
figure and what the snapshot holds). Rules: domain/rules/freshness (data_age_text).
"""

import dataclasses
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from diucs.application.actor import Actor
from diucs.application.ports.outbound.audit import AuditEntry, AuditRecord
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.domain.codes import Role, Status
from diucs.domain.errors import NotAllowed, NotFound
from diucs.domain.rules.freshness import data_age_text

REPLAY_USE_CASE: Final = "AuditReplay"
READ_ACTION: Final = "R"
ALLOWED_ROLES: Final = frozenset({Role.LEAD, Role.AUDIT})
FILTER_OPTIONS: Final = "FilterOptions"
REQUEST_BOOKING: Final = "RequestBooking"
RESPOND_TO_BOOKING: Final = "RespondToBooking"
SET_DECLINE_REASON: Final = "SetDeclineReason"
SHOWN_AS_OPTION: Final = "option"
NO_FIGURE: Final = "no figure"
NO_TIME_GIVEN: Final = "no time given"

_STATUS_WORDS: Final[Mapping[Status, str]] = {
    Status.ACCEPTING: "Accepting",
    Status.LIMITED: "Limited",
    Status.NOT_ACCEPTING: "Not accepting",
    Status.OVER_CAPACITY: "Over capacity",
    Status.NOT_UPDATED: "Not updated",
    Status.OUT_OF_HOURS: "Out of hours",
}

_CASE_LABELS: Final[Mapping[tuple[str, str], str]] = {
    ("OpenCase", "C"): "case opened",
    ("UpdateCase", "U"): "case updated",
    ("RequestBooking", "C"): "booking request sent",
    ("RecordDecline", "C"): "declined despite capacity",
    ("RecordOutcome", "U"): "outcome recorded",
}


@dataclass(frozen=True, slots=True)
class ReplayRow:
    service_name: str
    status: str
    value_text: str
    data_age_text: str
    criteria_version: int | None
    name_as_shown: bool = False
    """True when the name is the one the advisor saw (the snapshot keeps it, KI-474); False for a
    display written before names were kept, whose name is the service's name now."""


@dataclass(frozen=True, slots=True)
class TimelineItem:
    at: datetime
    label: str


@dataclass(frozen=True, slots=True)
class AuditReplay:
    reference: str
    shown_at: datetime | None
    rows: tuple[ReplayRow, ...]
    timeline: tuple[TimelineItem, ...]
    chain_ok: bool


@dataclass(frozen=True, slots=True)
class GetAuditReplayCommand:
    actor: Actor
    reference: str


def status_word(status: Status) -> str:
    return _STATUS_WORDS[status]


def age_words(seconds: int | None) -> str:
    """The data age as the advisor saw it: "9 min old", "2 hrs 10 min old", "just now"."""
    if seconds is None:
        return NO_TIME_GIVEN
    text = data_age_text(timedelta(seconds=seconds))
    if text == "just now":
        return text
    return f"{text.removesuffix(' ago')} old"


def _count(value: object) -> int | None:
    """A whole count of zero or more; a bool, a float or a negative number is not one."""
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def figure_text(status: Status, number: object, over_by: object) -> str | None:
    """What the service could take, or how far over capacity it was, and nothing otherwise. The
    number a snapshot holds for an over-capacity service is the used count (DEC-391): it is not a
    figure, so an over-capacity service shows its `over_by` or none. A service that is not
    accepting, not updated or out of hours shows none: its figure is not what it could take
    (H-190, KI-475)."""
    if status in (Status.ACCEPTING, Status.LIMITED):
        count = _count(number)
        return None if count is None else str(count)
    if status is Status.OVER_CAPACITY:
        over = _count(over_by)
        return None if over is None or over == 0 else f"+{over}"
    return None


def shown_order(rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """The rows of a display in the order the advisor saw them (H-193, KI-476): the options by the
    position they were shown at (nearest first), then the services that were not suitable in the
    order written. A display in which any option has no position (written before positions were
    kept) stays in the order written."""
    options = [row for row in rows if row.get("shown_as") == SHOWN_AS_OPTION]
    if any(_count(row.get("order")) is None for row in options):
        return list(rows)
    rest = [row for row in rows if row.get("shown_as") != SHOWN_AS_OPTION]
    return [*sorted(options, key=lambda row: int(row["order"])), *rest]


def _shown_name(row: Mapping[str, Any], names: Mapping[str, str]) -> tuple[str, bool]:
    """The name of a row, and whether it is the name the advisor saw. The snapshot's own name wins
    (a service renamed since is still shown as it was); an older row has the current name."""
    kept = row.get("name")
    if isinstance(kept, str) and kept.strip():
        return kept, True
    return names.get(row["id"], row["id"]), False


def replay_rows(
    snapshot_rows: Sequence[Mapping[str, Any]], names: Mapping[str, str]
) -> tuple[ReplayRow, ...]:
    rows: list[ReplayRow] = []
    for row in shown_order(snapshot_rows):
        name, as_shown = _shown_name(row, names)
        figure = figure_text(Status(row["status"]), row["number"], row.get("over_by"))
        rows.append(
            ReplayRow(
                service_name=name,
                status=status_word(Status(row["status"])),
                value_text=NO_FIGURE if figure is None else figure,
                data_age_text=age_words(row["data_age_seconds"]),
                criteria_version=row["criteria_version"],
                name_as_shown=as_shown,
            )
        )
    return tuple(rows)


def _count_options(snapshot: Mapping[str, Any] | None) -> int:
    if snapshot is None:
        return 0
    return sum(1 for row in snapshot["services"] if row["shown_as"] == SHOWN_AS_OPTION)


def timeline_item(record: AuditRecord) -> TimelineItem | None:
    """The timeline line for one audit record, or None for a replay (who looked is shown by the
    chain, not as a step of the case)."""
    entry = record.entry
    if entry.use_case == REPLAY_USE_CASE:
        return None
    at = entry.at
    if entry.use_case == FILTER_OPTIONS:
        count = _count_options(entry.snapshot)
        return TimelineItem(at, f"{count} option{'' if count == 1 else 's'} shown")
    if entry.use_case == RESPOND_TO_BOOKING and entry.snapshot is not None:
        return TimelineItem(at, f"{entry.snapshot['status']} by text")
    if entry.use_case == SET_DECLINE_REASON:
        return TimelineItem(at, "decline reason recorded")
    label = _CASE_LABELS.get((entry.use_case, entry.action), entry.use_case)
    return TimelineItem(at, label)


def options_display(records: Sequence[AuditRecord]) -> AuditRecord | None:
    """The FilterOptions display the advisor acted on: the last one before the first booking
    request, or the last one when no request was sent (DEC-390 item 3)."""
    last: AuditRecord | None = None
    for record in records:
        if record.entry.use_case == REQUEST_BOOKING:
            break
        if record.entry.use_case == FILTER_OPTIONS:
            last = record
    if last is not None:
        return last
    shown = [r for r in records if r.entry.use_case == FILTER_OPTIONS]
    return shown[-1] if shown else None


def check_replay_role(actor: Actor) -> None:
    if actor.role not in ALLOWED_ROLES:
        raise NotAllowed("only a shift lead or an audit reader may open a replay")


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.astimezone(UTC).isoformat()


class GetAuditReplay:
    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, command: GetAuditReplayCommand) -> AuditReplay:
        check_replay_role(command.actor)
        now = self._clock.now()
        async with self._uow_factory() as uow:
            case = await uow.cases.get_by_reference(command.reference)
            if case is None:
                raise NotFound("no case with this reference")

            case_records = await uow.audit.records_for(case.id)
            booking_ids = await _booking_ids(uow, case.id, case_records)
            booking_records: list[AuditRecord] = []
            for booking_id in booking_ids:
                booking_records.extend(await uow.audit.records_for(booking_id))
            # A record that names both the case and its booking (RequestBooking) is read twice: keep
            # one copy of each record, then order by time.
            unique = {record.id: record for record in [*case_records, *booking_records]}
            timeline_records = sorted(unique.values(), key=lambda r: r.entry.at)
            chosen = options_display(case_records)
            rows: tuple[ReplayRow, ...] = ()
            shown_at: datetime | None = None
            if chosen is not None and chosen.entry.snapshot is not None:
                snapshot_rows = chosen.entry.snapshot["services"]
                names = await _names(uow, [row["id"] for row in snapshot_rows])
                rows = replay_rows(snapshot_rows, names)
                shown_at = chosen.entry.at
            timeline = tuple(
                item for item in (timeline_item(r) for r in timeline_records) if item is not None
            )
            chain_ok = await uow.audit.verify_chain()

            await uow.audit.append(
                AuditEntry(
                    action=READ_ACTION,
                    use_case=REPLAY_USE_CASE,
                    actor=command.actor,
                    entity_ids=(case.id,),
                    snapshot=None,
                    at=now,
                )
            )
            await uow.commit()

        return AuditReplay(
            reference=case.reference,
            shown_at=shown_at,
            rows=rows,
            timeline=timeline,
            chain_ok=chain_ok,
        )


async def _booking_ids(uow: Any, case_id: str, case_records: Sequence[AuditRecord]) -> list[str]:
    """The ids of this case's bookings: the entity ids of its records that are bookings of this
    case (a service or the case itself is never one)."""
    candidates: list[str] = []
    for record in case_records:
        for entity_id in record.entry.entity_ids:
            if entity_id != case_id and entity_id not in candidates:
                candidates.append(entity_id)
    found: list[str] = []
    for candidate in candidates:
        booking = await uow.bookings.get(candidate)
        if booking is not None and booking.case_id == case_id:
            found.append(candidate)
    return found


async def _names(uow: Any, service_ids: Sequence[str]) -> dict[str, str]:
    names: dict[str, str] = {}
    for service_id in dict.fromkeys(service_ids):
        profile = await uow.services.get(service_id)
        if profile is not None:
            names[service_id] = profile.name
    return names


class ExportAuditReplay:
    """The replay as plain data for JSON or CSV. It reads through GetAuditReplay, so opening an
    export is recorded as a replay in the chain (DEC-390 item 6)."""

    def __init__(self, replay: GetAuditReplay) -> None:
        self._replay = replay

    async def execute(self, command: GetAuditReplayCommand) -> dict[str, Any]:
        result = await self._replay.execute(command)
        return {
            "reference": result.reference,
            "shown_at": _iso(result.shown_at),
            "chain_ok": result.chain_ok,
            "rows": [dataclasses.asdict(row) for row in result.rows],
            "timeline": [{"at": _iso(item.at), "label": item.label} for item in result.timeline],
        }
