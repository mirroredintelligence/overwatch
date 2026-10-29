"""RecordDecline and ListDeclinesSince: a referral the service declined although the board showed
capacity (U13).

The advisor records why a service declined a patient the board showed capacity for. The record
holds the status and number the advisor saw (from QueryBoard, read before this unit of work opens),
the reason, the case reference and the service. It is for the conversation with the service, not an
assessment of advisors: nothing returned here names who declined (DEC-293).

One unit of work writes the audit entry, the outbox message capacity.events DeclinedDespiteCapacity
and the replay record. A case that is closed, unknown or in another tenant is refused before any
write. The tenant comes from the unit of work (DEC-130 to DEC-134), never from the caller.
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from diucs.application.actor import Actor
from diucs.application.idempotency import IdempotencyStore
from diucs.application.ports.outbound.audit import AuditEntry, AuditRecord
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.outbox import OutboxMessage
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenancy import current_scope_or_none
from diucs.application.use_cases.open_case import (
    check_role,
    replay_key,
    tenant_scope,
)
from diucs.application.use_cases.query_board import BoardEntry, QueryBoard, QueryBoardQuery
from diucs.domain.codes import DeclineReason, Status
from diucs.domain.errors import Conflict, NotFound

DECLINE_USE_CASE: Final = "RecordDecline"
DECLINE_ACTION: Final = "C"
CAPACITY_TOPIC: Final = "capacity.events"
DECLINED_EVENT: Final = "DeclinedDespiteCapacity"


@dataclass(frozen=True, slots=True)
class DeclineRecord:
    """One decline, as a list shows it. Carries no practitioner: a decline is not an assessment of
    the advisor who recorded it (DEC-293)."""

    service_id: str
    reason: DeclineReason
    at: datetime


@dataclass(frozen=True, slots=True)
class RecordDeclineCommand:
    idempotency_key: str
    actor: Actor
    case_id: str
    service_id: str
    reason: DeclineReason


@dataclass(frozen=True, slots=True)
class RecordDeclineResult:
    case_id: str
    service_id: str
    reason: DeclineReason
    at: datetime


@dataclass(frozen=True, slots=True)
class _StoredDecline:
    """What the idempotency store keeps for a decline: the command's fingerprint and its result."""

    fingerprint: str
    result: RecordDeclineResult


def number_seen(effective_available: int | None, used: int | None) -> int | None:
    """The number the advisor saw: the effective figure, or the used count for a service that has
    no free count (occupied patients, DEC-033)."""
    if effective_available is not None:
        return effective_available
    return used


def decline_snapshot(
    reference: str,
    service_id: str,
    reason: DeclineReason,
    status_seen: Status,
    seen: int | None,
) -> dict[str, Any]:
    return {
        "reference": reference,
        "service_id": service_id,
        "reason": reason.value,
        "status_seen": status_seen.value,
        "number_seen": seen,
    }


def declines_from(records: Sequence[AuditRecord], since: datetime) -> list[DeclineRecord]:
    """The declines recorded at or after `since`, oldest first, read from the audit entries of
    RecordDecline only."""
    found: list[DeclineRecord] = []
    for record in records:
        entry = record.entry
        if entry.use_case != DECLINE_USE_CASE or entry.at < since:
            continue
        snapshot = entry.snapshot or {}
        found.append(
            DeclineRecord(
                service_id=str(snapshot["service_id"]),
                reason=DeclineReason(snapshot["reason"]),
                at=entry.at,
            )
        )
    return sorted(found, key=lambda decline: decline.at)


def _fingerprint(command: RecordDeclineCommand) -> str:
    body = repr(
        (
            command.case_id,
            command.service_id,
            command.reason.value,
            command.actor.role.value,
            command.actor.practitioner_id,
        )
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _same_command(stored: str, fingerprint: str) -> None:
    if stored != fingerprint:
        raise Conflict("this command key was used for a different decline")


def _declined_payload(service_id: str, reason: DeclineReason, now: datetime) -> dict[str, Any]:
    return {
        "service_id": service_id,
        "reason": reason.value,
        "at": now.astimezone(UTC).isoformat().replace("+00:00", "Z"),
    }


class RecordDecline:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        ids: IdGenerator,
        idempotency: IdempotencyStore,
        query_board: QueryBoard,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids
        self._idempotency = idempotency
        self._query_board = query_board

    async def execute(self, command: RecordDeclineCommand) -> RecordDeclineResult:
        check_role(command.actor)
        scope = tenant_scope(current_scope_or_none())
        fingerprint = _fingerprint(command)
        early = await self._idempotency.get(
            replay_key(DECLINE_USE_CASE, scope, command.idempotency_key)
        )
        if isinstance(early, _StoredDecline):
            _same_command(early.fingerprint, fingerprint)
            return early.result

        # The board is read in its own unit of work, before this one opens (P06).
        board = await self._query_board.execute(QueryBoardQuery(command.actor))
        seen = _entry_for(board.entries, command.service_id)

        async with self._uow_factory() as uow:
            key = replay_key(
                DECLINE_USE_CASE, tenant_scope(uow.unit_scope), command.idempotency_key
            )
            stored = await uow.idempotency.get(key)
            if isinstance(stored, _StoredDecline):
                _same_command(stored.fingerprint, fingerprint)
                return stored.result

            case = await uow.cases.get(command.case_id)
            if case is None:
                raise NotFound("no case with this id")
            if case.closed_at is not None:
                raise Conflict("the case is closed")

            now = self._clock.now()
            snapshot = decline_snapshot(
                case.reference,
                seen.service_id,
                command.reason,
                seen.status,
                number_seen(seen.effective_available, seen.used),
            )
            await uow.outbox.add(
                OutboxMessage(
                    id=self._ids.new_id(),
                    topic=CAPACITY_TOPIC,
                    event_type=DECLINED_EVENT,
                    payload=_declined_payload(seen.service_id, command.reason, now),
                    created_at=now,
                )
            )
            await uow.audit.append(
                AuditEntry(
                    action=DECLINE_ACTION,
                    use_case=DECLINE_USE_CASE,
                    actor=command.actor,
                    entity_ids=(case.id, seen.service_id),
                    snapshot=snapshot,
                    at=now,
                )
            )
            result = RecordDeclineResult(
                case_id=case.id, service_id=seen.service_id, reason=command.reason, at=now
            )
            await uow.idempotency.put(key, _StoredDecline(fingerprint, result))
            await uow.commit()
        return result


def _entry_for(entries: Sequence[BoardEntry], service_id: str) -> BoardEntry:
    """The board entry of an active service in this tenant. A service this tenant does not hold is
    not on its board, so it is not found."""
    for entry in entries:
        if entry.service_id == service_id:
            return entry
    raise NotFound("no active service with this id")


class ListDeclinesSince:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def execute(self, since: datetime) -> list[DeclineRecord]:
        # The audit port cannot filter by use case, so every record of the tenant's chain is read
        # and the declines picked out (known issue U13-1).
        async with self._uow_factory() as uow:
            records = await uow.audit.records()
        return declines_from(records, since)
