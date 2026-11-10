"""RetireService: the shift lead takes a service out of use for good (DEC-1356).

Suspending is for a pause. Retiring is for a service that has closed, was set up by mistake or has
been replaced. In one unit of work the service is made inactive (HealthcareService.active, its
Location and its Organization, each as a new version), so every list of active services leaves it
out: the board, the options, the phones list, the prompt ladder. Its prompt, reminder, phone-task
and escalation work is cancelled and every open request is expired with its timers cancelled.
Nothing is deleted: its reports, requests and audit trail stay in the record, and the audit names
the lead who retired it.

A service that is already inactive is a Conflict, so a second click or a stale page cannot retire
it twice.
"""

import hashlib
from dataclasses import dataclass
from typing import Final

from overwatch.application.actor import Actor
from overwatch.application.booking_effects import cancel_booking_timers, expired
from overwatch.application.ports.outbound.audit import AuditEntry
from overwatch.application.ports.outbound.clock import Clock
from overwatch.application.ports.outbound.outbox import outbox_message_for
from overwatch.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from overwatch.application.scheduling import cancel_work
from overwatch.application.tenancy import ScopeId, ScopeKind, TenantNotBound, current_scope
from overwatch.application.use_cases.suspend_service import SUSPENDED_WORK_KINDS, may_suspend
from overwatch.application.work import SCHEDULED
from overwatch.domain.errors import Conflict, NotAllowed, NotFound
from overwatch.domain.events import BookingExpired

USE_CASE: Final = "RetireService"
AUDIT_ACTION: Final = "U"
ONLY_LEAD: Final = "only the shift lead may retire a service"
NO_SERVICE: Final = "no service with this id"
ALREADY: Final = "this service is already retired"


@dataclass(frozen=True, slots=True)
class RetireServiceCommand:
    idempotency_key: str
    actor: Actor
    service_id: str


@dataclass(frozen=True, slots=True)
class RetireServiceResult:
    expired_requests: int


@dataclass(frozen=True, slots=True)
class _Stored:
    fingerprint: str
    result: RetireServiceResult


def _tenant_scope(unit_scope: ScopeId | None) -> ScopeId:
    if unit_scope is None or unit_scope.kind is not ScopeKind.TENANT:
        raise TenantNotBound
    return unit_scope


def _replay(stored: _Stored, fingerprint: str) -> RetireServiceResult:
    if stored.fingerprint != fingerprint:
        raise Conflict("this command key was used for a different retirement")
    return stored.result


class RetireService:
    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, command: RetireServiceCommand) -> RetireServiceResult:
        if not may_suspend(command.actor.role):
            raise NotAllowed(ONLY_LEAD)
        if command.actor.practitioner_id is None:
            raise NotAllowed("a retirement needs the lead who makes it")
        _tenant_scope(current_scope())
        fingerprint = hashlib.sha256(repr(("retire", command.service_id)).encode()).hexdigest()
        async with self._uow_factory() as uow:
            bound = _tenant_scope(uow.unit_scope)
            key = f"retire-service:{bound}:{command.idempotency_key}"
            stored = await uow.idempotency.get(key)
            if isinstance(stored, _Stored):
                return _replay(stored, fingerprint)
            profile = await uow.services.get(command.service_id)
            if profile is None:
                raise NotFound(NO_SERVICE)
            if not profile.active:
                raise Conflict(ALREADY)
            now = self._clock.now()
            requests = await uow.bookings.open_for_service(profile.id)
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
            await uow.services.set_inactive(profile.id)
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_ACTION,
                    use_case=USE_CASE,
                    actor=command.actor,
                    entity_ids=(profile.id, *(booking.id for booking in requests)),
                    snapshot={"expired_requests": len(requests)},
                    at=now,
                )
            )
            result = RetireServiceResult(expired_requests=len(requests))
            await uow.idempotency.put(key, _Stored(fingerprint, result))
            await uow.commit()
        return result
