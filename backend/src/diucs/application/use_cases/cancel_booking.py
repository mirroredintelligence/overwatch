"""CancelBooking: an advisor or a clinician cancels a booking before or after the service answered
(U20).

A requested booking becomes cancelled-before and its two timers are cancelled. A confirmed booking
becomes cancelled-after: it no longer reduces the effective available figure, so the slot goes back
on the board (confirmed_since counts only bookings whose status is exactly confirmed). The
service is told on its own channel with B6, and BookingCancelled is emitted.

One unit of work holds the change, its timers, its outbox messages, its echo and its audit entry
(DEC-106). The cancellation is replayed by its key (DEC-104), inside the bound tenant.
"""

import hashlib
from dataclasses import dataclass
from typing import Final

from diucs.application.actor import Actor
from diucs.application.booking_effects import cancel_booking_timers, text_reporter_role
from diucs.application.idempotency import IdempotencyStore
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.outbox import outbox_message_for
from diucs.application.ports.outbound.sealing import ContentSealer
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.sealed_send import queue_message
from diucs.application.tenancy import ScopeId, ScopeKind, TenantNotBound, current_scope
from diucs.domain.codes import BookingStatus, CancelReason, Channel
from diucs.domain.errors import Conflict, NotAllowed, NotFound, ValidationFailed
from diucs.domain.events import BookingCancelled
from diucs.domain.messages.catalogue import MessageId
from diucs.domain.messages.templates import render
from diucs.domain.rules.booking_response import advisor_may_cancel, cancel_target
from diucs.domain.rules.london_time import format_hhmm

USE_CASE: Final = "CancelBooking"
AUDIT_ACTION: Final = "U"
NO_BOOKING: Final = "no booking with this id"


@dataclass(frozen=True, slots=True)
class CancelBookingCommand:
    idempotency_key: str
    actor: Actor
    booking_id: str
    reason: CancelReason


@dataclass(frozen=True, slots=True)
class CancelBookingResult:
    booking_id: str
    status: BookingStatus


@dataclass(frozen=True, slots=True)
class _Stored:
    fingerprint: str
    result: CancelBookingResult


def command_key(scope: ScopeId, key: str) -> str:
    """The replay key, named by the tenant (lesson L160)."""
    return f"cancel-booking:{scope}:{key}"


def _fingerprint(command: CancelBookingCommand) -> str:
    body = repr(
        (
            command.booking_id,
            command.reason.value,
            command.actor.role.value,
            command.actor.practitioner_id,
        )
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _tenant_scope(unit_scope: ScopeId | None) -> ScopeId:
    if unit_scope is None or unit_scope.kind is not ScopeKind.TENANT:
        raise TenantNotBound
    return unit_scope


def _replay(stored: _Stored, fingerprint: str) -> CancelBookingResult:
    if stored.fingerprint != fingerprint:
        raise Conflict("this command key was used for a different cancellation")
    return stored.result


class CancelBooking:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        idempotency: IdempotencyStore,
        clock: Clock,
        ids: IdGenerator,
        sealer: ContentSealer,
    ) -> None:
        """`sealer` seals the B6 echo under its outbox message id (DEC-116)."""
        self._uow_factory = uow_factory
        self._idempotency = idempotency
        self._clock = clock
        self._ids = ids
        self._sealer = sealer

    async def execute(self, command: CancelBookingCommand) -> CancelBookingResult:
        if not advisor_may_cancel(command.actor.role):
            raise NotAllowed("only an advisor or a clinician may cancel a booking")
        if not isinstance(command.reason, CancelReason):
            raise ValidationFailed("reason", "is required: say why the booking is cancelled")
        fingerprint = _fingerprint(command)
        early = await self._idempotency.get(command_key(current_scope(), command.idempotency_key))
        if isinstance(early, _Stored):
            return _replay(early, fingerprint)

        async with self._uow_factory() as uow:
            scope = _tenant_scope(uow.unit_scope)
            key = command_key(scope, command.idempotency_key)
            stored = await uow.idempotency.get(key)
            if isinstance(stored, _Stored):
                return _replay(stored, fingerprint)

            booking = await uow.bookings.get(command.booking_id)
            if booking is None:
                raise NotFound(NO_BOOKING)
            target = cancel_target(booking.status)
            now = self._clock.now()
            was_requested = booking.status is BookingStatus.REQUESTED
            await uow.bookings.save(booking.with_status(target, now, command.reason.value))
            if was_requested:
                await cancel_booking_timers(uow, booking.id, now)
            await uow.outbox.add(
                outbox_message_for(
                    BookingCancelled(
                        booking_id=booking.id,
                        service_id=booking.service_id,
                        status=target,
                        at=now,
                    ),
                    id=f"booking-cancelled-{booking.id}",
                    now=now,
                )
            )
            role = await text_reporter_role(uow, booking.service_id, now)
            if role is not None:
                rendered = render(
                    MessageId.B6,
                    Channel.TEXT,
                    reference=booking.reference,
                    cancelled_at=format_hhmm(now),
                )
                await queue_message(
                    uow,
                    self._ids,
                    self._sealer,
                    scope=scope,
                    rendered=rendered,
                    recipient_role_id=role.id,
                    about_id=booking.id,
                    now=now,
                )
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_ACTION,
                    use_case=USE_CASE,
                    actor=command.actor,
                    entity_ids=(booking.id, booking.service_id),
                    snapshot={"status": target.value, "reason": command.reason.value},
                    at=now,
                )
            )
            result = CancelBookingResult(booking.id, target)
            await uow.idempotency.put(key, _Stored(fingerprint, result))
            await uow.commit()
        return result
