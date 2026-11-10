"""The replies the SMS webhook could not take in: list them, mark one handled, process one now
(DEC-1359).

A text reply reached the webhook, a service it needs failed on every attempt, and the sender was
told to send it again. The webhook keeps a record of it (`InboundReplyFailure`). The shift lead (or
the tenant administrator) sees the open ones, with who sent it when the phone hash still names an
active person, and either marks one handled (they dealt with it another way) or processes it now:
the stored reply is put on the same queue, with the same message id, that the webhook would have
used, and the record is closed as reprocessed. If putting it on the queue fails, nothing is closed
and the record stays open for another try.

Every change is one unit of work with an idempotency record and an audit entry (RetireService is
the pattern). The audit entry holds the message id and the step, never what the sender wrote.
"""

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from overwatch.application.actor import Actor
from overwatch.application.ports.outbound.audit import AuditEntry
from overwatch.application.ports.outbound.clock import Clock
from overwatch.application.ports.outbound.event_bus import BusMessage, EventBus
from overwatch.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from overwatch.application.tenancy import ScopeId, ScopeKind, TenantNotBound, current_scope
from overwatch.domain.codes import Role
from overwatch.domain.errors import Conflict, NotAllowed, NotFound, ValidationFailed
from overwatch.domain.model.inbound_reply import (
    FailedStep,
    InboundReplyFailure,
    ReplyStatus,
    Resolution,
)

USE_CASE_HANDLED: Final = "MarkFailedReplyHandled"
USE_CASE_REPROCESSED: Final = "ReprocessFailedReply"
AUDIT_ACTION: Final = "U"
ONLY_STAFF: Final = "only the shift lead or the administrator may work with these replies"
NO_REPLY: Final = "no waiting reply with this id"
NOT_OPEN: Final = "this reply has already been dealt with"

# What the webhook queues for the worker. The same names, so a reply put back on the queue here is
# the message the webhook would have sent (a test holds the two together).
REPLIES_QUEUE: Final = "inbound.replies"
REPLY_EVENT: Final = "SmsReceived"


def may_work_with_failed_replies(role: Role) -> bool:
    return role in (Role.LEAD, Role.TENANT_ADMIN)


def reply_message(failure: InboundReplyFailure, tenant_id: str) -> BusMessage:
    """The queue message for a stored reply: the message id is the sid (so the queue's own
    duplicate check treats a second put as the same message)."""
    return BusMessage(
        id=failure.sid,
        topic=REPLIES_QUEUE,
        event_type=REPLY_EVENT,
        payload={
            "phone_hash": failure.phone_hash,
            "text": failure.text,
            "received_at": failure.received_at.isoformat(),
            "provider_message_id": failure.sid,
        },
        tenant_id=tenant_id,
    )


@dataclass(frozen=True, slots=True)
class FailedReplyView:
    sid: str
    received_at: datetime
    step: FailedStep
    text: str
    sender_name: str | None
    """The active person who holds the phone hash, or None when no one does."""


def _check(actor: Actor) -> str:
    if not may_work_with_failed_replies(actor.role):
        raise NotAllowed(ONLY_STAFF)
    if actor.practitioner_id is None:
        raise NotAllowed("this needs the person who makes it")
    scope = current_scope()
    if scope is None or scope.kind is not ScopeKind.TENANT:
        raise TenantNotBound
    return scope.value


def _unit_tenant(uow: UnitOfWork) -> str:
    scope: ScopeId | None = uow.unit_scope
    if scope is None or scope.kind is not ScopeKind.TENANT:
        raise TenantNotBound
    return scope.value


class ListFailedReplies:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def execute(self, actor: Actor) -> list[FailedReplyView]:
        _check(actor)
        async with self._uow_factory() as uow:
            failures = await uow.inbound_replies.list_open()
            views: list[FailedReplyView] = []
            for failure in failures:
                sender = None
                try:
                    sender = await uow.people.find_by_phone_hash(failure.phone_hash)
                except Conflict:
                    sender = None  # two people on one hash: say nothing rather than guess
                views.append(
                    FailedReplyView(
                        sid=failure.sid,
                        received_at=failure.received_at,
                        step=failure.step,
                        text=failure.text,
                        sender_name=None if sender is None else sender.display_name,
                    )
                )
            return views


@dataclass(frozen=True, slots=True)
class FailedReplyCommand:
    idempotency_key: str
    actor: Actor
    sid: str


@dataclass(frozen=True, slots=True)
class _Stored:
    fingerprint: str
    resolution: Resolution


class _Resolver:
    use_case: str
    resolution: Resolution

    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def _before_close(self, failure: InboundReplyFailure, tenant_id: str) -> None:
        """Whatever must succeed before the record is closed. Raising leaves it open."""

    async def execute(self, command: FailedReplyCommand) -> Resolution:
        tenant_id = _check(command.actor)
        if not isinstance(command.sid, str) or not 2 <= len(command.sid) <= 64:
            raise ValidationFailed("sid", "not a message id")
        fingerprint = hashlib.sha256(repr((self.use_case, command.sid)).encode()).hexdigest()
        async with self._uow_factory() as uow:
            bound = _unit_tenant(uow)
            key = f"{self.use_case}:{bound}:{command.idempotency_key}"
            stored = await uow.idempotency.get(key)
            if isinstance(stored, _Stored):
                if stored.fingerprint != fingerprint:
                    raise Conflict("this command key was used for a different change")
                return stored.resolution
            failure = await uow.inbound_replies.get(command.sid)
            if failure is None:
                raise NotFound(NO_REPLY)
            if failure.status is not ReplyStatus.OPEN:
                raise Conflict(NOT_OPEN)
            await self._before_close(failure, tenant_id)
            now = self._clock.now()
            by = command.actor.practitioner_id
            assert by is not None
            if not await uow.inbound_replies.mark_resolved(
                failure.sid, resolution=self.resolution, by=by, at=now
            ):
                raise Conflict(NOT_OPEN)
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_ACTION,
                    use_case=self.use_case,
                    actor=command.actor,
                    entity_ids=(failure.sid,),
                    snapshot={"step": failure.step.value, "resolution": self.resolution.value},
                    at=now,
                )
            )
            await uow.idempotency.put(key, _Stored(fingerprint, self.resolution))
            await uow.commit()
        return self.resolution


class MarkFailedReplyHandled(_Resolver):
    use_case = USE_CASE_HANDLED
    resolution = Resolution.HANDLED


class ReprocessFailedReply(_Resolver):
    """Put the stored reply on the queue now. The queue is written before the record is closed, in
    the same unit of work; if the queue fails the error propagates, the unit rolls back and the
    record stays open. If the commit then fails after the queue took the message, a second try puts
    the same message id on the queue again, which the queue and the worker treat as one message."""

    use_case = USE_CASE_REPROCESSED
    resolution = Resolution.REPROCESSED

    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock, bus: EventBus) -> None:
        super().__init__(uow_factory, clock)
        self._bus = bus

    async def _before_close(self, failure: InboundReplyFailure, tenant_id: str) -> None:
        await self._bus.enqueue(REPLIES_QUEUE, reply_message(failure, tenant_id))
