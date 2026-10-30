"""Suspend and resume a tenant (TEN-073, DEC-507, audit F section 2.4, DEC-136 item 10).

The platform operator suspends a tenant for a fixed reason (a security incident, information
governance, clinical safety, contract, an operator's request) in one of two modes: `read-only`
(the tenant's administrator can still read, to export and to see what is wrong) and `blocked`
(nobody can, for a security incident). Resuming puts it back.

What a suspension is, and where each effect comes from:

- **The edge refuses at once, or within a minute.** The tenant record's status and epoch are what
  the REST edge checks every token against (`tenant_gate.py`, TEN-018). Suspending writes the record
  (a compare and set on the epoch and status read) and raises the epoch, so a token issued before is
  refused even after a resume. A process that has the record cached reads it again at most
  `RECORD_TTL` (60 seconds) later, and the use case tells the serving process's gate to forget the
  tenant at once (`on_changed`, `auth.forget_tenant`). That is the bound the task states: a
  suspension takes effect within the token cache interval, never at the token's expiry.
- **The workers skip it.** The outbox relay serves the directory's active tenants and the queue
  consumers bind a message's tenant only when the directory lists it as active (DEC-352), so nothing
  is relayed, projected or processed for a suspended tenant; a message for it is dead-lettered as
  `tenant-unknown`, and what is pending in its outbox waits.
- **Its boards go Not updated by staleness.** Nothing prompts, so nothing is reported, and the board
  and the network view (TEN-057) read the figures as old. No event is written on suspension, because
  the relay would hold it until the resume and publish it late.

Resuming is the unsafe direction if it is half done: an active tenant whose services are never
prompted again is silent, and a silent service is the hazard the missed-report ladder exists for
(H-13). So the tenant's own work comes first and the record last: in one unit of work, for each
active service that is not suspended by its lead, the stale prompt (due while the tenant was
suspended) is cancelled, the next prompt is scheduled from the service's own times (once: a prompt
still ahead is kept) and a `StatusChanged` is written so the boards recompute; then the record is
saved. A resume that stopped between the two is run again: the work is marked under the tenant and
the epoch it was done for, and is not done twice.

The operator and the tenant are as for the rest of the lifecycle (`tenant_admin.py`): the platform
operator, named, of the bound tenant; no data access. Free text is never a reason.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from diucs.application.actor import Actor
from diucs.application.idempotency import format_instant
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.outbox import outbox_message_for
from diucs.application.ports.outbound.tenant_registry import TenantRegistry
from diucs.application.ports.outbound.tenants import TenantDirectory
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.scheduling import cancel_work, schedule_work
from diucs.application.tenancy import ScopeId
from diucs.application.tenant_settings import TenantZones, as_zones, read_settings
from diucs.application.use_cases.tenant_admin import (
    AUDIT_UPDATE,
    MOVED,
    NO_TENANT,
    OperatorUseCase,
    _audit,
    _unit_scope,
)
from diucs.application.work import SCHEDULED, WorkKind
from diucs.domain.codes import Status
from diucs.domain.errors import Conflict, DomainError, NotFound
from diucs.domain.events import StatusChanged
from diucs.domain.model.flags import SERVICE_FLAG_SUSPENDED
from diucs.domain.model.tenant import SuspendMode, SuspendReason, TenantStatus
from diucs.domain.rules.schedule import next_due
from diucs.domain.rules.status import compute_status
from diucs.domain.rules.tenant_lifecycle import resume_tenant, suspend_tenant

TenantChanged = Callable[[str], None]
"""Told the tenant's id after its record changed, so the serving process can drop what it cached
about it (`auth.forget_tenant`). The use case never waits on it and a failing one is not caught."""

DONE_MARK: Final = "tenant-resume"


def resume_marker(scope: ScopeId, epoch: int) -> str:
    """The key under which a resume's tenant-scope work is recorded: the tenant and the epoch the
    record was at when the work was done, so a run repeated after a partial failure sees it."""
    return f"{DONE_MARK}:{scope}:{epoch}"


def resume_event_id(epoch: int, service_id: str) -> str:
    """The id of a service's StatusChanged for a resume to this epoch: the same on every run."""
    return f"tenant-resume-{epoch}-{service_id}"


@dataclass(frozen=True, slots=True)
class SuspendTenantCommand:
    actor: Actor
    mode: SuspendMode
    reason: SuspendReason


@dataclass(frozen=True, slots=True)
class SuspendTenantResult:
    tenant_id: str
    epoch: int
    mode: SuspendMode


class SuspendTenant(OperatorUseCase):
    def __init__(
        self,
        tenants: TenantDirectory,
        registry: TenantRegistry,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        on_changed: tuple[TenantChanged, ...] = (),
    ) -> None:
        super().__init__(tenants, uow_factory, clock)
        self._registry = registry
        self._on_changed = on_changed

    async def execute(self, command: SuspendTenantCommand) -> SuspendTenantResult:
        _, scope = self._begin(command.actor)
        tenant = await self._tenants.get(scope.value)
        if tenant is None:
            raise NotFound(NO_TENANT)
        # Only an active tenant is suspended; any other move is refused and nothing is written.
        suspended = suspend_tenant(tenant, command.mode, command.reason, self._clock.now())
        # The record first: the suspension must not wait for anything else, and a failure after it
        # leaves a tenant that is safely stopped.
        if not await self._registry.save(
            suspended, expected_epoch=tenant.epoch, expected_status=TenantStatus.ACTIVE
        ):
            raise Conflict(MOVED)
        for changed in self._on_changed:
            changed(scope.value)
        async with self._uow_factory() as uow:
            _unit_scope(uow)
            await _audit(
                uow,
                self._clock,
                command.actor,
                "SuspendTenant",
                AUDIT_UPDATE,
                f"tenant-{scope.value}",
                {
                    "mode": command.mode.value,
                    "reason": command.reason.value,
                    "epoch": suspended.epoch,
                },
            )
            await uow.commit()
        return SuspendTenantResult(scope.value, suspended.epoch, command.mode)


@dataclass(frozen=True, slots=True)
class ResumeTenantCommand:
    actor: Actor


@dataclass(frozen=True, slots=True)
class ResumeTenantResult:
    tenant_id: str
    epoch: int
    services_prompted: int
    """How many services had their next prompt scheduled by this resume."""
    services_announced: int
    """How many services had a StatusChanged written for the boards."""
    resumed_again: bool = False
    """True when the tenant-scope work had been done by an earlier run and was not done again."""


class ResumeTenant(OperatorUseCase):
    def __init__(
        self,
        tenants: TenantDirectory,
        registry: TenantRegistry,
        uow_factory: UnitOfWorkFactory,
        ids: IdGenerator,
        clock: Clock,
        zones: TenantZones | None = None,
        on_changed: tuple[TenantChanged, ...] = (),
    ) -> None:
        super().__init__(tenants, uow_factory, clock)
        self._registry = registry
        self._ids = ids
        self._zones = as_zones(zones)
        self._on_changed = on_changed

    async def execute(self, command: ResumeTenantCommand) -> ResumeTenantResult:
        _, scope = self._begin(command.actor)
        tenant = await self._tenants.get(scope.value)
        if tenant is None:
            raise NotFound(NO_TENANT)
        now = self._clock.now()
        # Only a suspended tenant is resumed (`InvalidTransition` otherwise, nothing written).
        resumed = resume_tenant(tenant, now)

        prompted = announced = 0
        again = False
        async with self._uow_factory() as uow:
            _unit_scope(uow)
            marker = resume_marker(scope, tenant.epoch)
            if await uow.idempotency.get(marker) is not None:
                again = True
            else:
                settings = await read_settings(uow, self._zones)
                for profile in await uow.services.list_active():
                    flags = await uow.flags.service_flags(profile.id)
                    if any(f.code == SERVICE_FLAG_SUSPENDED and f.active for f in flags):
                        # The lead's own suspension of this service stands (U36).
                        continue
                    works = await uow.scheduled_work.for_about(profile.id, WorkKind.PROMPT_DUE)
                    waiting = [w for w in works if w.status == SCHEDULED]
                    for stale in (w for w in waiting if w.due_at <= now):
                        await cancel_work(uow, stale, now)
                    if not any(w.due_at > now for w in waiting):
                        due = next_due(profile, now, settings.policy, settings.zone)
                        if due is None:
                            raise DomainError(
                                "a profile with available times always has a next due instant"
                            )
                        await schedule_work(
                            uow,
                            self._ids,
                            kind=WorkKind.PROMPT_DUE,
                            about_id=profile.id,
                            due_at=due,
                            now=now,
                        )
                        prompted += 1
                    latest = await uow.capacity.latest(profile.id)
                    confirmed = (
                        []
                        if latest is None
                        else await uow.bookings.confirmed_since(profile.id, latest.effective_at)
                    )
                    status: Status = compute_status(
                        profile, latest, confirmed, now, settings.policy, settings.zone
                    ).status
                    await uow.outbox.add(
                        outbox_message_for(
                            StatusChanged(
                                service_id=profile.id,
                                before=Status.NOT_UPDATED,
                                after=status,
                                at=now,
                            ),
                            id=resume_event_id(resumed.epoch, profile.id),
                            now=now,
                        )
                    )
                    announced += 1
                await uow.idempotency.put(marker, format_instant(now))
                await _audit(
                    uow,
                    self._clock,
                    command.actor,
                    "ResumeTenant",
                    AUDIT_UPDATE,
                    f"tenant-{scope.value}",
                    {
                        "epoch": resumed.epoch,
                        "servicesPrompted": prompted,
                        "servicesAnnounced": announced,
                    },
                )
                await uow.commit()
        # The record last (see the module's text): the tenant is active only when its services are
        # prompted again.
        if not await self._registry.save(
            resumed, expected_epoch=tenant.epoch, expected_status=TenantStatus.SUSPENDED
        ):
            raise Conflict(MOVED)
        for changed in self._on_changed:
            changed(scope.value)
        return ResumeTenantResult(
            tenant_id=scope.value,
            epoch=resumed.epoch,
            services_prompted=prompted,
            services_announced=announced,
            resumed_again=again,
        )
