"""RespondToBooking: the service confirms or declines an open booking request (U18).

The reply can come from text, a one-tap link or the app. It moves the booking Task out of
`requested`, cancels the phone prompt and the expiry, queues the echo (B4 or B5) to the service,
and tells the advisor through a BookingResponded event. A reply to an expired booking changes
nothing and is reported as already final. SetDeclineReason gives a decline its reason later, once.

One unit of work holds the booking, its timers, its outbox messages, its echo and its audit entry
(DEC-106). A reply is replayed by its key (DEC-104), inside the tenant the unit is bound to.
"""

import hashlib
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final, Literal

from diucs.application.actor import Actor
from diucs.application.booking_effects import cancel_booking_timers, queue_echo, text_reporter_role
from diucs.application.idempotency import IdempotencyStore
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.outbox import outbox_message_for
from diucs.application.ports.outbound.sealing import ContentSealer
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenancy import ScopeId, ScopeKind, TenantNotBound, current_scope
from diucs.domain.codes import BookingStatus, Channel, DeclineReason, ReportSource, Role
from diucs.domain.errors import Conflict, NotAllowed, NotFound, ValidationFailed
from diucs.domain.events import BookingResponded
from diucs.domain.messages.catalogue import MessageId
from diucs.domain.messages.templates import RenderedMessage, render
from diucs.domain.model.booking import Booking
from diucs.domain.rules.booking_response import (
    DECLINE,
    echo_message,
    may_set_decline_reason,
    plan_response,
    responder_may_act,
)
from diucs.domain.rules.london_time import format_hhmm

USE_CASE: Final = "RespondToBooking"
SET_REASON_USE_CASE: Final = "SetDeclineReason"
AUDIT_ACTION: Final = "U"
NOT_YOUR_BOOKING: Final = "this booking is not for your service"
NO_BOOKING: Final = "no booking with this id"
RESPONDER_ROLES: Final = frozenset({Role.REPORTER, Role.ANONYMOUS_LINK})


@dataclass(frozen=True, slots=True)
class RespondToBookingCommand:
    idempotency_key: str
    actor: Actor
    booking_id: str
    decision: Literal["confirm", "decline"]
    reason: DeclineReason | None = None
    channel: ReportSource = ReportSource.TEXT


@dataclass(frozen=True, slots=True)
class RespondToBookingResult:
    booking_id: str
    status: BookingStatus
    responded_at: datetime | None
    already_final: bool


@dataclass(frozen=True, slots=True)
class SetDeclineReasonCommand:
    idempotency_key: str
    actor: Actor
    booking_id: str
    reason: DeclineReason


@dataclass(frozen=True, slots=True)
class _Stored:
    """What the idempotency store keeps for a reply key: the result and the reply's fingerprint."""

    fingerprint: str
    result: RespondToBookingResult


def command_key(scope: ScopeId, key: str) -> str:
    """The replay key, named by the tenant (lesson L160): the same key in another tenant is another
    command."""
    return f"respond-booking:{scope}:{key}"


def _fingerprint(command: RespondToBookingCommand) -> str:
    body = repr(
        (
            command.booking_id,
            command.decision,
            None if command.reason is None else command.reason.value,
            command.actor.role.value,
            command.actor.practitioner_id,
        )
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _tenant_scope(unit_scope: ScopeId | None) -> ScopeId:
    if unit_scope is None or unit_scope.kind is not ScopeKind.TENANT:
        raise TenantNotBound
    return unit_scope


def _replay(stored: _Stored, fingerprint: str) -> RespondToBookingResult:
    if stored.fingerprint != fingerprint:
        raise Conflict("this command key was used for a different reply")
    return stored.result


def _rendered_echo(
    message: MessageId, booking: Booking, service_name: str, now: datetime
) -> RenderedMessage:
    """B4 names the confirmation time; B5 names only the reference (D16)."""
    if message is MessageId.B4:
        return render(
            message,
            Channel.TEXT,
            reference=booking.reference,
            service=service_name,
            confirmed_at=format_hhmm(now),
        )
    return render(message, Channel.TEXT, reference=booking.reference)


class RespondToBooking:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        idempotency: IdempotencyStore,
        clock: Clock,
        ids: IdGenerator,
        sealer: ContentSealer,
    ) -> None:
        """`sealer` seals the echo under its outbox message id (DEC-116). The echo is sent by the
        I10 senders; this use case sends nothing."""
        self._uow_factory = uow_factory
        self._idempotency = idempotency
        self._clock = clock
        self._ids = ids
        self._sealer = sealer

    async def execute(self, command: RespondToBookingCommand) -> RespondToBookingResult:
        if command.actor.role not in RESPONDER_ROLES:
            raise NotAllowed(NOT_YOUR_BOOKING)
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
            if not responder_may_act(
                command.actor.role, command.actor.service_ids, booking.service_id
            ):
                raise NotAllowed(NOT_YOUR_BOOKING)
            target = plan_response(booking.status, command.decision)
            if target is None:
                return RespondToBookingResult(
                    booking.id, booking.status, booking.responded_at, already_final=True
                )
            if command.decision != DECLINE and command.reason is not None:
                raise ValidationFailed("reason", "only a decline has a reason")

            now = self._clock.now()
            reason = None if command.reason is None else command.reason.value
            await uow.bookings.save(booking.with_status(target, now, reason))
            await cancel_booking_timers(uow, booking.id, now)
            await uow.outbox.add(
                outbox_message_for(
                    BookingResponded(
                        booking_id=booking.id,
                        service_id=booking.service_id,
                        status=target,
                        at=now,
                    ),
                    id=self._ids.new_id(),
                    now=now,
                )
            )
            role = await text_reporter_role(uow, booking.service_id, now)
            if role is not None:
                profile = await uow.services.get(booking.service_id)
                if profile is None:
                    raise NotFound(NO_BOOKING)
                rendered = _rendered_echo(echo_message(target), booking, profile.name, now)
                await queue_echo(
                    uow,
                    self._ids,
                    self._sealer,
                    scope=scope,
                    rendered=rendered,
                    booking=booking,
                    recipient_role_id=role.id,
                    now=now,
                )
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_ACTION,
                    use_case=USE_CASE,
                    actor=command.actor,
                    entity_ids=(booking.id, booking.service_id),
                    snapshot={"status": target.value, "channel": command.channel.value},
                    at=now,
                )
            )
            result = RespondToBookingResult(booking.id, target, now, already_final=False)
            await uow.idempotency.put(key, _Stored(fingerprint, result))
            await uow.commit()
        return result


class SetDeclineReason:
    """Gives a declined booking its reason, once (U18). The reason is the advisor's record only:
    it is not echoed, and it changes no state but the reason."""

    def __init__(
        self, uow_factory: UnitOfWorkFactory, idempotency: IdempotencyStore, clock: Clock
    ) -> None:
        self._uow_factory = uow_factory
        self._idempotency = idempotency
        self._clock = clock

    async def execute(self, command: SetDeclineReasonCommand) -> None:
        if command.actor.role not in RESPONDER_ROLES:
            raise NotAllowed(NOT_YOUR_BOOKING)
        async with self._uow_factory() as uow:
            booking = await uow.bookings.get(command.booking_id)
            if booking is None:
                raise NotFound(NO_BOOKING)
            if not responder_may_act(
                command.actor.role, command.actor.service_ids, booking.service_id
            ):
                raise NotAllowed(NOT_YOUR_BOOKING)
            may_set_decline_reason(booking.status, reason_set=booking.reason is not None)
            now = self._clock.now()
            await uow.bookings.save(replace(booking, reason=command.reason.value))
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_ACTION,
                    use_case=SET_REASON_USE_CASE,
                    actor=command.actor,
                    entity_ids=(booking.id, booking.service_id),
                    snapshot={"reason": command.reason.value},
                    at=now,
                )
            )
            await uow.commit()
