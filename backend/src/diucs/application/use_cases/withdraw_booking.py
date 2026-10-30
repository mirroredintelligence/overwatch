"""Exceptions after a confirmed booking: WithdrawBooking, ReportNotReached,
AcknowledgeWithdrawal and EscalateWithdrawal (U21).

A service may withdraw a confirmed booking (now full, staffing, cannot reach the patient, other) or
report it not reached (not at the address, no answer, gone to hospital, other). Both start only from
confirmed and alert the advisor at once (BookingWithdrawn, BookingNotReached on booking.events).

A withdrawal also schedules an escalation WITHDRAWAL_ESCALATE (decision DEC-400, not
ESCALATE_TO_LEAD, which the missed-report ladder owns) at the tenant's withdrawal window. The advisor's
acknowledgement cancels it. If the escalation fires while the withdrawal is still unacknowledged,
WithdrawalEscalated goes to alerts.events for the shift lead, once: the work is marked done in the
same unit of work, so a second delivery does nothing.

Every command is replayed by its key inside the tenant the unit is bound to (DEC-104), every
change is audited, and the change, its audit entry and its outbox messages share one unit of work
(DEC-106).
"""

import hashlib
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final

from diucs.application.actor import Actor, timer_actor
from diucs.application.idempotency import IdempotencyStore
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.outbox import outbox_message_for
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.scheduling import cancel_work, schedule_work
from diucs.application.tenancy import (
    ScopeId,
    ScopeKind,
    TenantNotBound,
    current_scope,
    current_tenant,
)
from diucs.application.work import DONE, SCHEDULED, ScheduledWork, WorkKind
from diucs.domain.codes import BookingStatus, NotReachedReason, Role, WithdrawReason
from diucs.domain.errors import Conflict, NotAllowed, NotFound, ValidationFailed
from diucs.domain.events import BookingNotReached, BookingWithdrawn, WithdrawalEscalated
from diucs.domain.model.booking import Booking
from diucs.domain.model.tenant_policy import DEFAULT_POLICY
from diucs.domain.rules.booking_exceptions import (
    checked_not_reached_reason,
    checked_withdraw_reason,
    not_reached_target,
    withdraw_target,
)
from diucs.domain.rules.booking_response import advisor_may_cancel, responder_may_act

AUDIT_ACTION: Final = "U"
WITHDRAW_USE_CASE: Final = "WithdrawBooking"
NOT_REACHED_USE_CASE: Final = "ReportNotReached"
ACKNOWLEDGE_USE_CASE: Final = "AcknowledgeWithdrawal"
ESCALATE_USE_CASE: Final = "EscalateWithdrawal"
NO_BOOKING: Final = "no booking with this id"
NO_TIMER: Final = "no escalation of this kind for this booking"
NOT_YOUR_BOOKING: Final = "this booking is not for your service"
NOT_WITHDRAWN: Final = "only a withdrawn booking can be acknowledged"
RESPONDERS: Final = frozenset({Role.REPORTER, Role.ANONYMOUS_LINK})


@dataclass(frozen=True, slots=True)
class WithdrawBookingCommand:
    idempotency_key: str
    actor: Actor
    booking_id: str
    reason: WithdrawReason


@dataclass(frozen=True, slots=True)
class WithdrawBookingResult:
    booking_id: str
    status: BookingStatus
    escalation_due_at: datetime


@dataclass(frozen=True, slots=True)
class ReportNotReachedCommand:
    idempotency_key: str
    actor: Actor
    booking_id: str
    reason: NotReachedReason


@dataclass(frozen=True, slots=True)
class ReportNotReachedResult:
    booking_id: str
    status: BookingStatus


@dataclass(frozen=True, slots=True)
class AcknowledgeWithdrawalCommand:
    idempotency_key: str
    actor: Actor
    booking_id: str


@dataclass(frozen=True, slots=True)
class AcknowledgeWithdrawalResult:
    booking_id: str
    cancelled_escalation: bool


@dataclass(frozen=True, slots=True)
class EscalateWithdrawalCommand:
    work_id: str
    booking_id: str


@dataclass(frozen=True, slots=True)
class EscalateWithdrawalResult:
    acted: bool


@dataclass(frozen=True, slots=True)
class _Stored[R]:
    """What the idempotency store keeps for a command key: its fingerprint and its result."""

    fingerprint: str
    result: R


def command_key(name: str, scope: ScopeId, key: str) -> str:
    """The replay key, named by the command and the tenant (lesson L160)."""
    return f"{name}:{scope}:{key}"


def _fingerprint(*parts: object) -> str:
    return hashlib.sha256(repr(parts).encode("utf-8")).hexdigest()


def _tenant_scope(unit_scope: ScopeId | None) -> ScopeId:
    if unit_scope is None or unit_scope.kind is not ScopeKind.TENANT:
        raise TenantNotBound
    return unit_scope


def _replay[R](stored: _Stored[object], fingerprint: str, kind: type[R]) -> R:
    if stored.fingerprint != fingerprint or not isinstance(stored.result, kind):
        raise Conflict("this command key was used for a different command")
    return stored.result


async def _booking_for_responder(uow: UnitOfWork, actor: Actor, booking_id: str) -> Booking:
    booking = await uow.bookings.get(booking_id)
    if booking is None:
        raise NotFound(NO_BOOKING)
    if not responder_may_act(actor.role, actor.service_ids, booking.service_id):
        raise NotAllowed(NOT_YOUR_BOOKING)
    return booking


class WithdrawBooking:
    """The service withdraws a confirmed booking: withdrawn, BookingWithdrawn, and an escalation
    scheduled at the withdrawal window."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        idempotency: IdempotencyStore,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        self._uow_factory = uow_factory
        self._idempotency = idempotency
        self._clock = clock
        self._ids = ids

    async def execute(self, command: WithdrawBookingCommand) -> WithdrawBookingResult:
        if command.actor.role not in RESPONDERS:
            raise NotAllowed(NOT_YOUR_BOOKING)
        reason = checked_withdraw_reason(command.reason)
        fingerprint = _fingerprint(command.booking_id, reason.value, command.actor.role.value)
        early = await self._idempotency.get(
            command_key(WITHDRAW_USE_CASE, current_scope(), command.idempotency_key)
        )
        if isinstance(early, _Stored):
            return _replay(early, fingerprint, WithdrawBookingResult)

        async with self._uow_factory() as uow:
            scope = _tenant_scope(uow.unit_scope)
            key = command_key(WITHDRAW_USE_CASE, scope, command.idempotency_key)
            stored = await uow.idempotency.get(key)
            if isinstance(stored, _Stored):
                return _replay(stored, fingerprint, WithdrawBookingResult)

            booking = await _booking_for_responder(uow, command.actor, command.booking_id)
            target = withdraw_target(booking.status)
            now = self._clock.now()
            due = now + DEFAULT_POLICY.withdrawal_escalate_after
            await uow.bookings.save(booking.with_status(target, now, reason.value))
            await uow.outbox.add(
                outbox_message_for(
                    BookingWithdrawn(
                        booking_id=booking.id,
                        service_id=booking.service_id,
                        reason=reason,
                        at=now,
                    ),
                    id=f"booking-withdrawn-{booking.id}",
                    now=now,
                )
            )
            await schedule_work(
                uow,
                self._ids,
                kind=WorkKind.WITHDRAWAL_ESCALATE,
                about_id=booking.id,
                due_at=due,
                now=now,
            )
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_ACTION,
                    use_case=WITHDRAW_USE_CASE,
                    actor=command.actor,
                    entity_ids=(booking.id, booking.service_id),
                    snapshot={"status": target.value, "reason": reason.value},
                    at=now,
                )
            )
            result = WithdrawBookingResult(booking.id, target, due)
            await uow.idempotency.put(key, _Stored(fingerprint, result))
            await uow.commit()
        return result


class ReportNotReached:
    """The service reports its confirmed patient not reached: not-reached, BookingNotReached, and
    no timer (U21, [ASSUMED])."""

    def __init__(
        self, uow_factory: UnitOfWorkFactory, idempotency: IdempotencyStore, clock: Clock
    ) -> None:
        self._uow_factory = uow_factory
        self._idempotency = idempotency
        self._clock = clock

    async def execute(self, command: ReportNotReachedCommand) -> ReportNotReachedResult:
        if command.actor.role not in RESPONDERS:
            raise NotAllowed(NOT_YOUR_BOOKING)
        reason = checked_not_reached_reason(command.reason)
        fingerprint = _fingerprint(command.booking_id, reason.value, command.actor.role.value)
        early = await self._idempotency.get(
            command_key(NOT_REACHED_USE_CASE, current_scope(), command.idempotency_key)
        )
        if isinstance(early, _Stored):
            return _replay(early, fingerprint, ReportNotReachedResult)

        async with self._uow_factory() as uow:
            scope = _tenant_scope(uow.unit_scope)
            key = command_key(NOT_REACHED_USE_CASE, scope, command.idempotency_key)
            stored = await uow.idempotency.get(key)
            if isinstance(stored, _Stored):
                return _replay(stored, fingerprint, ReportNotReachedResult)

            booking = await _booking_for_responder(uow, command.actor, command.booking_id)
            target = not_reached_target(booking.status)
            now = self._clock.now()
            await uow.bookings.save(booking.with_status(target, now, reason.value))
            await uow.outbox.add(
                outbox_message_for(
                    BookingNotReached(
                        booking_id=booking.id,
                        service_id=booking.service_id,
                        reason=reason,
                        at=now,
                    ),
                    id=f"booking-not-reached-{booking.id}",
                    now=now,
                )
            )
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_ACTION,
                    use_case=NOT_REACHED_USE_CASE,
                    actor=command.actor,
                    entity_ids=(booking.id, booking.service_id),
                    snapshot={"status": target.value, "reason": reason.value},
                    at=now,
                )
            )
            result = ReportNotReachedResult(booking.id, target)
            await uow.idempotency.put(key, _Stored(fingerprint, result))
            await uow.commit()
        return result


class AcknowledgeWithdrawal:
    """The advisor has seen a withdrawal: the escalation is cancelled. Acknowledging after the
    escalation has run changes nothing but is still audited."""

    def __init__(
        self, uow_factory: UnitOfWorkFactory, idempotency: IdempotencyStore, clock: Clock
    ) -> None:
        self._uow_factory = uow_factory
        self._idempotency = idempotency
        self._clock = clock

    async def execute(self, command: AcknowledgeWithdrawalCommand) -> AcknowledgeWithdrawalResult:
        if not advisor_may_cancel(command.actor.role):
            raise NotAllowed("only an advisor or a clinician may acknowledge a withdrawal")
        fingerprint = _fingerprint(command.booking_id, command.actor.role.value)
        early = await self._idempotency.get(
            command_key(ACKNOWLEDGE_USE_CASE, current_scope(), command.idempotency_key)
        )
        if isinstance(early, _Stored):
            return _replay(early, fingerprint, AcknowledgeWithdrawalResult)

        async with self._uow_factory() as uow:
            scope = _tenant_scope(uow.unit_scope)
            key = command_key(ACKNOWLEDGE_USE_CASE, scope, command.idempotency_key)
            stored = await uow.idempotency.get(key)
            if isinstance(stored, _Stored):
                return _replay(stored, fingerprint, AcknowledgeWithdrawalResult)

            booking = await uow.bookings.get(command.booking_id)
            if booking is None:
                raise NotFound(NO_BOOKING)
            if booking.status is not BookingStatus.WITHDRAWN:
                raise ValidationFailed("booking", NOT_WITHDRAWN)
            now = self._clock.now()
            cancelled = False
            for work in await uow.scheduled_work.for_about(
                booking.id, WorkKind.WITHDRAWAL_ESCALATE
            ):
                if work.status == SCHEDULED:
                    await cancel_work(uow, work, now)
                    cancelled = True
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_ACTION,
                    use_case=ACKNOWLEDGE_USE_CASE,
                    actor=command.actor,
                    entity_ids=(booking.id, booking.service_id),
                    snapshot={"cancelled_escalation": cancelled},
                    at=now,
                )
            )
            result = AcknowledgeWithdrawalResult(booking.id, cancelled)
            await uow.idempotency.put(key, _Stored(fingerprint, result))
            await uow.commit()
        return result


class EscalateWithdrawal:
    """The escalation timer of a withdrawal (run by the scheduled-work consumer). If the withdrawal
    is still unacknowledged, WithdrawalEscalated is emitted once; a timer that is not scheduled, or
    whose booking is no longer withdrawn, does nothing."""

    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, command: EscalateWithdrawalCommand) -> EscalateWithdrawalResult:
        async with self._uow_factory() as uow:
            work = await _escalation_work(uow, command.work_id, command.booking_id)
            if work is None:
                return EscalateWithdrawalResult(acted=False)
            booking = await uow.bookings.get(command.booking_id)
            if booking is None:
                raise NotFound(NO_BOOKING)
            await uow.scheduled_work.save(replace(work, status=DONE))
            if booking.status is not BookingStatus.WITHDRAWN:
                await uow.commit()
                return EscalateWithdrawalResult(acted=False)
            now = self._clock.now()
            await uow.outbox.add(
                outbox_message_for(
                    WithdrawalEscalated(
                        booking_id=booking.id, service_id=booking.service_id, at=now
                    ),
                    id=f"withdrawal-escalated-{booking.id}",
                    now=now,
                )
            )
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_ACTION,
                    use_case=ESCALATE_USE_CASE,
                    actor=timer_actor(current_tenant()),
                    entity_ids=(booking.id, booking.service_id),
                    snapshot={"status": booking.status.value},
                    at=now,
                )
            )
            await uow.commit()
        return EscalateWithdrawalResult(acted=True)


async def _escalation_work(uow: UnitOfWork, work_id: str, booking_id: str) -> ScheduledWork | None:
    """The stored escalation, or None when it is not scheduled any more (done or cancelled)."""
    work = await uow.scheduled_work.get(work_id)
    if work.kind is not WorkKind.WITHDRAWAL_ESCALATE or work.about_id != booking_id:
        raise NotFound(NO_TIMER)
    return work if work.status == SCHEDULED else None
