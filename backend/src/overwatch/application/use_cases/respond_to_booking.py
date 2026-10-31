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
from datetime import datetime, timedelta
from typing import Final, Literal

from diucs.application.actor import Actor
from diucs.application.booking_effects import cancel_booking_timers, echo_role, queue_echo
from diucs.application.idempotency import IdempotencyStore
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.outbox import outbox_message_for
from diucs.application.ports.outbound.sealing import ContentSealer
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.tenancy import ScopeId, ScopeKind, TenantNotBound, current_scope
from diucs.application.use_cases.send_prompts import LinkTokenServiceFactory
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
class ChangeLinkRequest:
    """The change link a confirmation gives the service (L02): its purpose, the phone it is tied to
    and how long it lasts. The use case issues it in the unit that records the confirmation, so a
    crash cannot leave a confirmed booking with no change link, or a link for a booking that is not
    confirmed (KI-483)."""

    purpose: str
    phone_hash: str | None
    lifetime: timedelta


@dataclass(frozen=True, slots=True)
class RespondToBookingCommand:
    idempotency_key: str
    actor: Actor
    booking_id: str
    decision: Literal["confirm", "decline"]
    reason: DeclineReason | None = None
    channel: ReportSource = ReportSource.TEXT
    change_link: ChangeLinkRequest | None = None


@dataclass(frozen=True, slots=True)
class RespondToBookingResult:
    booking_id: str
    status: BookingStatus
    responded_at: datetime | None
    already_final: bool
    change_token: str | None = None
    """The change link's token, only on the call that confirmed. It is a bearer secret and is never
    stored in the replay record: a replay of the same command returns None."""


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
    message: MessageId, booking: Booking, service_name: str, now: datetime, channel: Channel
) -> RenderedMessage:
    """B4 names the confirmation time; B5 names only the reference (D16). The channel is the
    reporter's own: text, email or push (H-135)."""
    if message is MessageId.B4:
        return render(
            message,
            channel,
            reference=booking.reference,
            service=service_name,
            confirmed_at=format_hhmm(now),
        )
    return render(message, channel, reference=booking.reference)


class RespondToBooking:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        idempotency: IdempotencyStore,
        clock: Clock,
        ids: IdGenerator,
        sealer: ContentSealer,
        *,
        link_tokens: LinkTokenServiceFactory | None = None,
    ) -> None:
        """`sealer` seals the echo under its outbox message id (DEC-116). The echo is sent by the
        I10 senders; this use case sends nothing. `link_tokens` builds the link service over the
        unit's own repository, for a command that asks for a change link (KI-483)."""
        self._uow_factory = uow_factory
        self._idempotency = idempotency
        self._clock = clock
        self._ids = ids
        self._sealer = sealer
        self._link_tokens = link_tokens

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
            change_token = await self._issue_change_token(uow, command, booking, target, now)
            echo = await echo_role(uow, booking.service_id, now)
            if echo is not None:
                role, channel = echo
                profile = await uow.services.get(booking.service_id)
                if profile is None:
                    raise NotFound(NO_BOOKING)
                rendered = _rendered_echo(echo_message(target), booking, profile.name, now, channel)
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
            # The replay record never holds the bearer: a replay returns the result with no token.
            await uow.idempotency.put(key, _Stored(fingerprint, result))
            await uow.commit()
        return replace(result, change_token=change_token)

    async def _issue_change_token(
        self,
        uow: UnitOfWork,
        command: RespondToBookingCommand,
        booking: Booking,
        target: BookingStatus,
        now: datetime,
    ) -> str | None:
        """The change link of a confirmation, issued in the caller's unit (KI-483). A decline, or a
        command that asks for none, issues none."""
        link = command.change_link
        if link is None or target is not BookingStatus.CONFIRMED:
            return None
        if self._link_tokens is None:
            raise ValidationFailed("change_link", "this use case was built without link tokens")
        return await self._link_tokens(uow.link_tokens).issue(
            link.purpose, booking.id, link.phone_hash, now + link.lifetime
        )


@dataclass(frozen=True, slots=True)
class _StoredReason:
    """What the idempotency store keeps for a decline-reason key: the command's fingerprint. The
    command has no result to give back (KI-356)."""

    fingerprint: str


def reason_key(scope: ScopeId, key: str) -> str:
    """The replay key of a decline reason, named by the tenant (lesson L160)."""
    return f"set-decline-reason:{scope}:{key}"


def _reason_fingerprint(command: SetDeclineReasonCommand) -> str:
    body = repr(
        (
            command.booking_id,
            command.reason.value,
            command.actor.role.value,
            command.actor.practitioner_id,
        )
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _check_reason_replay(stored: object, fingerprint: str) -> bool:
    """True when `stored` is this command's own earlier record (a replay: nothing more to do), False
    when the key holds nothing. A key that was used for a different command is a Conflict."""
    if stored is None:
        return False
    if not isinstance(stored, _StoredReason) or stored.fingerprint != fingerprint:
        raise Conflict("this command key was used for a different reason")
    return True


class SetDeclineReason:
    """Gives a declined booking its reason, once (U18). The reason is the advisor's record only:
    it is not echoed, and it changes no state but the reason. The same command under the same key
    replays and changes nothing more (KI-356)."""

    def __init__(
        self, uow_factory: UnitOfWorkFactory, idempotency: IdempotencyStore, clock: Clock
    ) -> None:
        self._uow_factory = uow_factory
        self._idempotency = idempotency
        self._clock = clock

    async def execute(self, command: SetDeclineReasonCommand) -> None:
        if command.actor.role not in RESPONDER_ROLES:
            raise NotAllowed(NOT_YOUR_BOOKING)
        fingerprint = _reason_fingerprint(command)
        early = await self._idempotency.get(reason_key(current_scope(), command.idempotency_key))
        if _check_reason_replay(early, fingerprint):
            return
        async with self._uow_factory() as uow:
            scope = _tenant_scope(uow.unit_scope)
            key = reason_key(scope, command.idempotency_key)
            if _check_reason_replay(await uow.idempotency.get(key), fingerprint):
                return
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
            await uow.idempotency.put(key, _StoredReason(fingerprint))
            await uow.commit()
