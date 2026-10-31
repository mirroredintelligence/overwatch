"""SuspendService and ResumeService: the shift lead takes a service off the board, and puts it back
(U36).

Suspending writes a service flag `suspended` in one unit of work, so the status rule reads the
service as not-updated ("Not updated, phone to confirm" on the board) and it leaves the options (the
criteria hard filter reads only unsuspended services). Its prompt, reminder, phone-task and
escalation work is cancelled, every open request is expired with its timers cancelled, the service
is told with K4 on its text channel, and a StatusChanged event is emitted.

Resuming needs two checks: the register number was phoned, and the reason was resolved. It clears
the flag, schedules the next prompt-due from the service's own times (D04), and emits
StatusChanged.
Both are audited under the lead who made them.

One unit of work holds every effect, so a failure before the commit leaves none of them (DEC-106).
The tenant's coordination team name for K4 is read before the unit opens, from the tenant directory.
"""

import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Final

from diucs.application.actor import Actor
from diucs.application.booking_effects import cancel_booking_timers, expired, text_reporter_role
from diucs.application.idempotency import IdempotencyStore, format_instant
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.outbox import outbox_message_for
from diucs.application.ports.outbound.sealing import ContentSealer
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.scheduling import cancel_work, schedule_work
from diucs.application.sealed_send import queue_message
from diucs.application.tenancy import ScopeId, ScopeKind, TenantNotBound, current_scope
from diucs.application.work import SCHEDULED, WorkKind
from diucs.domain.codes import Channel, Role, Status
from diucs.domain.errors import Conflict, DomainError, NotAllowed, NotFound, ValidationFailed
from diucs.domain.events import BookingExpired, StatusChanged
from diucs.domain.messages.catalogue import MessageId
from diucs.domain.messages.templates import render
from diucs.domain.model.flags import SERVICE_FLAG_SUSPENDED, ServiceFlag
from diucs.domain.model.service import ServiceProfile
from diucs.domain.model.tenant import TenantWording
from diucs.domain.model.tenant_policy import TenantPolicy
from diucs.domain.rules.schedule import next_due
from diucs.domain.rules.status import compute_status

USE_CASE_SUSPEND: Final = "SuspendService"
USE_CASE_RESUME: Final = "ResumeService"
AUDIT_ACTION: Final = "U"
RESUME_REASON: Final = "resumed after the phone check and the resolved reason"
NO_SERVICE: Final = "no service with this id"
ONLY_LEAD: Final = "only the shift lead may suspend or resume a service"
SUSPENDED_WORK_KINDS: Final = frozenset(
    {WorkKind.PROMPT_DUE, WorkKind.REMINDER, WorkKind.PHONE_TASK, WorkKind.ESCALATE_TO_LEAD}
)


WordingFor = Callable[[ScopeId], Awaitable[TenantWording | None]]
"""The tenant's wording for the scope, or None when it has none. K4 names the tenant's coordination
team (TEN-022), so it needs this. The tenant configuration read path is not built yet, so the caller
that wires SuspendService supplies it (a known issue); without it the suspension still happens and
K4 is not queued."""


class SuspendReason(StrEnum):
    SUSPECTED_FALSE_REPORTS = "suspected-false-reports"
    CLOSED_UNEXPECTEDLY = "closed-unexpectedly"
    CONTACT_UNREACHABLE = "contact-unreachable"
    OTHER = "other"


def may_suspend(role: Role) -> bool:
    """Only the shift lead suspends or resumes a service (U36)."""
    return role is Role.LEAD


def suspend_reason_of(value: str) -> SuspendReason:
    """The suspend reason for its text. A reason outside the four is refused."""
    try:
        return SuspendReason(value)
    except ValueError:
        raise ValidationFailed("reason", "must be one of the four suspend reasons") from None


def require_resume_checks(*, phoned_register_number: bool, reason_resolved: bool) -> None:
    """A resume needs both checks: the register number was phoned, and the reason was resolved."""
    if not phoned_register_number:
        raise ValidationFailed("phoned_register_number", "the register number must be phoned")
    if not reason_resolved:
        raise ValidationFailed("reason_resolved", "the reason for the suspension must be resolved")


@dataclass(frozen=True, slots=True)
class SuspendServiceCommand:
    idempotency_key: str
    actor: Actor
    service_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class SuspendServiceResult:
    expired_requests: int
    notified: bool = False
    """True when K4 was queued to the service (a text reporter and the tenant's wording)."""


@dataclass(frozen=True, slots=True)
class ResumeServiceCommand:
    idempotency_key: str
    actor: Actor
    service_id: str
    phoned_register_number: bool
    reason_resolved: bool


@dataclass(frozen=True, slots=True)
class ResumeServiceResult:
    status: Status
    next_due_at: datetime


@dataclass(frozen=True, slots=True)
class _Stored:
    fingerprint: str
    result: object


def _tenant_scope(unit_scope: ScopeId | None) -> ScopeId:
    if unit_scope is None or unit_scope.kind is not ScopeKind.TENANT:
        raise TenantNotBound
    return unit_scope


def _fingerprint(*parts: object) -> str:
    return hashlib.sha256(repr(parts).encode("utf-8")).hexdigest()


def _suspended(flags: list[ServiceFlag]) -> bool:
    return any(flag.code == SERVICE_FLAG_SUSPENDED and flag.active for flag in flags)


async def _status_now(
    uow: UnitOfWork, profile: ServiceProfile, now: datetime, policy: TenantPolicy
) -> Status:
    """The status the board shows for this service at `now`, as the status rule reads it."""
    report = await uow.capacity.latest(profile.id)
    confirmed = (
        []
        if report is None
        else await uow.bookings.confirmed_since(profile.id, report.effective_at)
    )
    return compute_status(profile, report, confirmed, now, policy).status


def _status_key(service_id: str, now: datetime) -> str:
    return f"status-changed-{service_id}-{format_instant(now)}"


class SuspendService:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        idempotency: IdempotencyStore,
        clock: Clock,
        ids: IdGenerator,
        sealer: ContentSealer,
        wording_for: WordingFor,
        policy: TenantPolicy,
    ) -> None:
        """`policy` is the tenant's policy (TEN-021): the status rule reads it. The caller that
        wires this use case supplies it from the tenant's configuration."""
        self._uow_factory = uow_factory
        self._idempotency = idempotency
        self._clock = clock
        self._ids = ids
        self._sealer = sealer
        self._wording_for = wording_for
        self._policy = policy

    async def execute(self, command: SuspendServiceCommand) -> SuspendServiceResult:
        if not may_suspend(command.actor.role):
            raise NotAllowed(ONLY_LEAD)
        if command.actor.practitioner_id is None:
            raise NotAllowed("a suspension needs the lead who makes it")
        reason = suspend_reason_of(command.reason)
        scope = _tenant_scope(current_scope())
        fingerprint = _fingerprint("suspend", command.service_id, reason.value)
        key = f"suspend-service:{scope}:{command.idempotency_key}"
        early = await self._idempotency.get(key)
        if isinstance(early, _Stored):
            return _replay(early, fingerprint)

        async with self._uow_factory() as uow:
            bound = _tenant_scope(uow.unit_scope)
            key = f"suspend-service:{bound}:{command.idempotency_key}"
            stored = await uow.idempotency.get(key)
            if isinstance(stored, _Stored):
                return _replay(stored, fingerprint)
            profile = await uow.services.get(command.service_id)
            if profile is None:
                raise NotFound(NO_SERVICE)
            if _suspended(await uow.flags.service_flags(command.service_id)):
                raise Conflict("this service is already suspended")
            wording = await self._wording_for(bound)

            now = self._clock.now()
            before = await _status_now(uow, profile, now, self._policy)
            requests = await uow.bookings.open_for_service(profile.id)
            await uow.flags.set_service_flag(
                ServiceFlag(
                    service_id=profile.id,
                    code=SERVICE_FLAG_SUSPENDED,
                    active=True,
                    reason=reason.value,
                    actor_id=command.actor.practitioner_id,
                    at=now,
                    expired_count=len(requests),
                )
            )
            for work in await uow.scheduled_work.for_about(profile.id):
                if work.kind in SUSPENDED_WORK_KINDS and work.status == SCHEDULED:
                    await cancel_work(uow, work, now)
            for booking in requests:
                await uow.bookings.save(expired(booking, now))
                await cancel_booking_timers(uow, booking.id, now)
                await uow.outbox.add(
                    outbox_message_for(
                        BookingExpired(booking_id=booking.id, service_id=profile.id, at=now),
                        id=f"booking-expired-{booking.id}",
                        now=now,
                    )
                )
            role = await text_reporter_role(uow, profile.id, now)
            notified = role is not None and wording is not None
            if role is not None and wording is not None:
                rendered = render(
                    MessageId.K4,
                    Channel.TEXT,
                    service=profile.name,
                    coordination_team_name=wording.coordination_team_name,
                )
                await queue_message(
                    uow,
                    self._ids,
                    self._sealer,
                    scope=bound,
                    rendered=rendered,
                    recipient_role_id=role.id,
                    about_id=profile.id,
                    now=now,
                )
            await uow.outbox.add(
                outbox_message_for(
                    StatusChanged(
                        service_id=profile.id, before=before, after=Status.NOT_UPDATED, at=now
                    ),
                    id=_status_key(profile.id, now),
                    now=now,
                )
            )
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_ACTION,
                    use_case=USE_CASE_SUSPEND,
                    actor=command.actor,
                    entity_ids=(profile.id, *(booking.id for booking in requests)),
                    snapshot={"reason": reason.value, "expired_requests": len(requests)},
                    at=now,
                )
            )
            result = SuspendServiceResult(expired_requests=len(requests), notified=notified)
            await uow.idempotency.put(key, _Stored(fingerprint, result))
            await uow.commit()
        return result


def _replay(stored: _Stored, fingerprint: str) -> SuspendServiceResult:
    if stored.fingerprint != fingerprint:
        raise Conflict("this command key was used for a different suspension")
    assert isinstance(stored.result, SuspendServiceResult)
    return stored.result


class ResumeService:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        idempotency: IdempotencyStore,
        clock: Clock,
        ids: IdGenerator,
        policy: TenantPolicy,
    ) -> None:
        self._uow_factory = uow_factory
        self._idempotency = idempotency
        self._clock = clock
        self._ids = ids
        self._policy = policy

    async def execute(self, command: ResumeServiceCommand) -> ResumeServiceResult:
        if not may_suspend(command.actor.role):
            raise NotAllowed(ONLY_LEAD)
        if command.actor.practitioner_id is None:
            raise NotAllowed("a resume needs the lead who makes it")
        require_resume_checks(
            phoned_register_number=command.phoned_register_number,
            reason_resolved=command.reason_resolved,
        )
        scope = _tenant_scope(current_scope())
        fingerprint = _fingerprint("resume", command.service_id)
        early = await self._idempotency.get(f"resume-service:{scope}:{command.idempotency_key}")
        if isinstance(early, _Stored):
            return _replay_resume(early, fingerprint)

        async with self._uow_factory() as uow:
            bound = _tenant_scope(uow.unit_scope)
            key = f"resume-service:{bound}:{command.idempotency_key}"
            stored = await uow.idempotency.get(key)
            if isinstance(stored, _Stored):
                return _replay_resume(stored, fingerprint)
            profile = await uow.services.get(command.service_id)
            if profile is None:
                raise NotFound(NO_SERVICE)
            if not _suspended(await uow.flags.service_flags(command.service_id)):
                raise Conflict("this service is not suspended")

            now = self._clock.now()
            await uow.flags.set_service_flag(
                ServiceFlag(
                    service_id=profile.id,
                    code=SERVICE_FLAG_SUSPENDED,
                    active=False,
                    reason=RESUME_REASON,
                    actor_id=command.actor.practitioner_id,
                    at=now,
                )
            )
            resumed = replace(profile, suspended=False)
            status = await _status_now(uow, resumed, now, self._policy)
            due = next_due(resumed, now, self._policy)
            if due is None:
                raise DomainError("a profile with available times always has a next due instant")
            await schedule_work(
                uow,
                self._ids,
                kind=WorkKind.PROMPT_DUE,
                about_id=profile.id,
                due_at=due,
                now=now,
            )
            await uow.outbox.add(
                outbox_message_for(
                    StatusChanged(
                        service_id=profile.id,
                        before=Status.NOT_UPDATED,
                        after=status,
                        at=now,
                    ),
                    id=_status_key(profile.id, now),
                    now=now,
                )
            )
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_ACTION,
                    use_case=USE_CASE_RESUME,
                    actor=command.actor,
                    entity_ids=(profile.id,),
                    snapshot={"status": status.value, "next_due_at": format_instant(due)},
                    at=now,
                )
            )
            result = ResumeServiceResult(status=status, next_due_at=due)
            await uow.idempotency.put(key, _Stored(fingerprint, result))
            await uow.commit()
        return result


def _replay_resume(stored: _Stored, fingerprint: str) -> ResumeServiceResult:
    if stored.fingerprint != fingerprint:
        raise Conflict("this command key was used for a different resume")
    assert isinstance(stored.result, ResumeServiceResult)
    return stored.result
