"""What a clinician is shown about the advisor's request besides the case (W9G, DEC-1030 to 1035).

Two reads of a request, both for the clinician who holds it and for no one else:

  * `ReadWhatAdvisorSaw`: the display of the options the advisor had when they asked, as the audit
    snapshot of that FilterOptions display holds it (the request keeps which one, `snapshot_ref`,
    when it is made). One line per service: its status, its figure, how old the figure was and, for
    a service that was not suitable, why. Capacity and the reason only: never a postcode, the
    district, a person's id or a service's id. A figure is what the service could take, or how far
    over it was; never a used count that could be read as free places (DEC-391, H-190).
  * `ReadAdvisorContact`: the number to phone the advisor on. The advisor's work phone, when the
    tenant holds one for an active advisor (a ProtectedContact, DEC-856), else the tenant's advisor
    line (a role number in the tenant's configuration), else none. The number is returned whole to
    the holder and is never logged, audited or put in telemetry; the audit entry says only which way
    it was found.

The clinician who holds the request is the one it is locked to and whose lock has not lapsed, as
the queue reads it; a lapsed lock is back in the queue and is held by no one. Every other caller
reads NotFound, the answer for an id that is not there, so a refusal tells nothing.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Final

from diucs.application.actor import Actor
from diucs.application.ports.outbound.audit import AuditEntry, AuditRecord
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.use_cases.audit_replay import age_words, status_word
from diucs.domain.codes import Role, Status
from diucs.domain.errors import NotFound
from diucs.domain.model.clinical import ClinicalRequestRecord
from diucs.domain.model.people import work_contact_key
from diucs.domain.model.tenant import ContactKind
from diucs.domain.model.tenant_policy import DEFAULT_POLICY
from diucs.domain.rules.clinical_queue import return_if_idle
from diucs.domain.rules.freshness import STALE_WARNING_AFTER

FILTER_OPTIONS: Final = "FilterOptions"
CONTACT_USE_CASE: Final = "ReadAdvisorContact"
READ_ACTION: Final = "R"
NO_REQUEST: Final = "no clinical advice request with this id"
SHOWN_AS_OPTION: Final = "option"
SHOWN_AS_NOT_SUITABLE: Final = "not-suitable"
SEEN_SHOWN: Final = "shown"
SEEN_NONE: Final = "none"
SEEN_UNREADABLE: Final = "unreadable"
"""The three states of a read: a display is kept and read; none is kept for this request; one is
named and cannot be read (it is missing, is not a display of this case, or a row is not valid)."""
NO_NAME: Final = "A service that is no longer listed"
VIA_WORK_PHONE: Final = "work-phone"
VIA_LINE: Final = "advisor-line"
VIA_NONE: Final = "none"

_WHY_TEXT: Final[Mapping[str, str]] = {
    "not-accepting": "Not accepting",
    "out-of-hours": "Out of hours",
    "not-updated": "Not updated",
    "suspended": "Suspended",
    "outside-criteria": "Outside its criteria",
    "criteria-not-current": "Criteria not current",
}
NOT_SUITABLE_TEXT: Final = "Not suitable"
_STATUS_WHY: Final[Mapping[str, str]] = {
    "not-accepting": "not-accepting",
    "out-of-hours": "out-of-hours",
    "not-updated": "not-updated",
}
"""A snapshot written before the reason was kept is explained from its status where the status
says it; any other is only "not suitable"."""


@dataclass(frozen=True, slots=True)
class SeenLine:
    service: str
    shown_as: str
    status: str
    status_text: str
    figure: str | None
    age: str
    stale: bool
    why: str | None
    criteria_version: int | None


@dataclass(frozen=True, slots=True)
class WhatAdvisorSaw:
    state: str
    shown_at: datetime | None
    lines: tuple[SeenLine, ...]

    @property
    def options(self) -> int:
        return sum(1 for line in self.lines if line.shown_as == SHOWN_AS_OPTION)


@dataclass(frozen=True, slots=True)
class AdvisorContact:
    via: str | None
    phone: str | None
    name: str | None


def _count(value: object) -> int | None:
    """A whole count of zero or more; a bool, a float or a negative number is not one."""
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def figure_text(status: Status, number: object, over_by: object) -> str | None:
    """What the service could take, or how far over capacity it was, and nothing otherwise. The
    number a snapshot holds for an over-capacity service is the used count (DEC-391): it is not a
    figure, so an over-capacity service shows its `over_by` or none. A service that is not
    accepting, not updated or out of hours shows none: its figure is not what it could take."""
    if status in (Status.ACCEPTING, Status.LIMITED):
        count = _count(number)
        return None if count is None else str(count)
    if status is Status.OVER_CAPACITY:
        over = _count(over_by)
        return None if over is None or over == 0 else f"+{over}"
    return None


def why_text(row: Mapping[str, Any]) -> str | None:
    """Why a service was not suitable, in words; None for a service that was an option."""
    if row.get("shown_as") != SHOWN_AS_NOT_SUITABLE:
        return None
    code = row.get("reason") or _STATUS_WHY.get(str(row.get("status")))
    return _WHY_TEXT.get(str(code), NOT_SUITABLE_TEXT)


def _checked_age(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    raise ValueError("data age is not a whole number of seconds")


def _checked_version(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
        return value
    raise ValueError("criteria version is not a version number")


def seen_lines(rows: Sequence[Mapping[str, Any]], names: Mapping[str, str]) -> tuple[SeenLine, ...]:
    """The lines of a display. A row that cannot be read (an unknown status or shown-as, an age or
    version of the wrong kind, a missing key) refuses the whole display: half a display shown to a
    clinician would read as the whole of it."""
    lines: list[SeenLine] = []
    for row in rows:
        status = Status(row["status"])
        shown_as = row["shown_as"]
        if shown_as not in (SHOWN_AS_OPTION, SHOWN_AS_NOT_SUITABLE):
            raise ValueError("a row is shown as an option or as not suitable")
        age_seconds = _checked_age(row["data_age_seconds"])
        lines.append(
            SeenLine(
                service=names.get(row["id"], NO_NAME),
                shown_as=shown_as,
                status=status.value,
                status_text=status_word(status),
                figure=figure_text(status, row["number"], row.get("over_by")),
                age=age_words(age_seconds),
                stale=age_seconds is not None and age_seconds > STALE_WARNING_AFTER.total_seconds(),
                why=why_text(row),
                criteria_version=_checked_version(row["criteria_version"]),
            )
        )
    return tuple(lines)


def pinned_display(
    records: Sequence[AuditRecord], requester_id: str, asked_at: datetime
) -> AuditRecord | None:
    """The display a request keeps: the last FilterOptions display of the case that the asking
    advisor had at or before the moment they asked (a later display, or another advisor's, is not
    what this advisor saw when they asked). None when they had none."""
    chosen: AuditRecord | None = None
    for record in records:
        entry = record.entry
        if (
            entry.use_case == FILTER_OPTIONS
            and entry.actor.practitioner_id == requester_id
            and entry.at <= asked_at
            and (chosen is None or entry.at >= chosen.entry.at)
        ):
            chosen = record
    return chosen


def _held_by(record: ClinicalRequestRecord, actor: Actor, now: datetime) -> ClinicalRequestRecord:
    """The record as the queue reads it now, if this clinician holds it; else NotFound. Held is
    locked to this clinician with the lock not lapsed, or advised by this clinician."""
    if actor.role is not Role.CLINICAL or actor.practitioner_id is None:
        raise NotFound(NO_REQUEST)
    released = replace(record, request=return_if_idle(record.request, now, DEFAULT_POLICY))
    if released.request.taken_by != actor.practitioner_id:
        raise NotFound(NO_REQUEST)
    return released


async def _display_of(uow: UnitOfWork, record: ClinicalRequestRecord) -> AuditRecord | None:
    """The display the request names, or None when it is not one of this case's displays."""
    for candidate in await uow.audit.records_for(record.request.case_id):
        entry = candidate.entry
        if (
            candidate.id == record.snapshot_ref
            and entry.use_case == FILTER_OPTIONS
            and tuple(entry.entity_ids[:1]) == (record.request.case_id,)
        ):
            return candidate
    return None


async def _names(uow: UnitOfWork, service_ids: Sequence[str]) -> dict[str, str]:
    names: dict[str, str] = {}
    for service_id in dict.fromkeys(service_ids):
        profile = await uow.services.get(service_id)
        if profile is not None:
            names[service_id] = profile.name
    return names


@dataclass(frozen=True, slots=True)
class ReadWhatAdvisorSaw:
    uow_factory: UnitOfWorkFactory
    clock: Clock

    async def execute(self, actor: Actor, request_id: str) -> WhatAdvisorSaw:
        unreadable = WhatAdvisorSaw(SEEN_UNREADABLE, None, ())
        async with self.uow_factory() as uow:
            record = await uow.clinical_requests.get(request_id)
            if record is None:
                raise NotFound(NO_REQUEST)
            held = _held_by(record, actor, self.clock.now())
            if held.snapshot_ref is None:
                return WhatAdvisorSaw(SEEN_NONE, None, ())
            display = await _display_of(uow, held)
            snapshot = None if display is None else display.entry.snapshot
            if display is None or snapshot is None:
                return unreadable
            try:
                rows = snapshot["services"]
                names = await _names(uow, [row["id"] for row in rows])
                lines = seen_lines(rows, names)
            except KeyError, ValueError, TypeError:
                return unreadable
        return WhatAdvisorSaw(SEEN_SHOWN, display.entry.at, lines)


@dataclass(frozen=True, slots=True)
class ReadAdvisorContact:
    uow_factory: UnitOfWorkFactory
    clock: Clock

    async def execute(self, actor: Actor, request_id: str) -> AdvisorContact:
        async with self.uow_factory() as uow:
            record = await uow.clinical_requests.get(request_id)
            if record is None:
                raise NotFound(NO_REQUEST)
            now = self.clock.now()
            held = _held_by(record, actor, now)
            if held.request.advised_at is not None:
                # Advised: the advisor has the advice and the request is no longer being worked.
                raise NotFound(NO_REQUEST)
            contact = await self._contact(uow, held.requester_id)
            await uow.audit.append(
                AuditEntry(
                    action=READ_ACTION,
                    use_case=CONTACT_USE_CASE,
                    actor=actor,
                    entity_ids=(request_id,),
                    snapshot={"via": contact.via or VIA_NONE},
                    at=now,
                )
            )
            await uow.commit()
        return contact

    @staticmethod
    async def _contact(uow: UnitOfWork, requester_id: str) -> AdvisorContact:
        advisor = await uow.people.get_practitioner(requester_id)
        if advisor is not None:
            phone = await uow.contacts.get_phone(work_contact_key(requester_id))
            if phone:
                return AdvisorContact(VIA_WORK_PHONE, phone, advisor.display_name)
        for contact in await uow.tenant_config.contacts():
            if contact.kind is ContactKind.ADVISOR_LINE and contact.value:
                return AdvisorContact(VIA_LINE, contact.value, None)
        return AdvisorContact(None, None, None)
