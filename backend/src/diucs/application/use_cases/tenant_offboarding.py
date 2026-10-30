"""Start a tenant's offboarding (TEN-075; the notice period and the rest of offboarding are
TEN-074, DEC-136 item 10, audit F section 2.4).

The platform operator moves an active or suspended tenant into `offboarding`: the thirty-day notice
period begins (`start_offboarding`, `OFFBOARDING_NOTICE`). That is all this does. The export of the
tenant's data, the end of its network memberships, the quarantine of its numbers, the completion of
the notice and the two-operator purge are TEN-074's; none of them is started here.

What starting does, and what it leaves for TEN-074:

- the registry record moves by compare and set on the epoch and status the operator read, so two
  operators cannot both start it and a tenant that changed since is a `Conflict`;
- the serving process forgets the tenant (`on_changed`), so the edge reads the new status at once
  and within a minute everywhere: an offboarding tenant is not open at the REST edge. Until TEN-074
  gives the tenant's administrator a read-only door for the export, offboarding is also the end of
  the tenant's sign-in (known issue), which is why the operator must type the tenant's id to start
  it;
- the operator's step is written in the tenant's own chain, with the instant the notice period
  ends.

The operator and the tenant are as for the rest of the lifecycle (`tenant_admin.py`): the platform
operator, named, of the bound tenant; no data access.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Final

from diucs.application.actor import Actor
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.tenant_registry import TenantRegistry
from diucs.application.ports.outbound.tenants import TenantDirectory
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.tenant_admin import (
    AUDIT_UPDATE,
    MOVED,
    NO_TENANT,
    OperatorUseCase,
    _audit,
    _unit_scope,
)
from diucs.application.use_cases.tenant_suspend import TenantChanged
from diucs.domain.errors import Conflict, NotFound, ValidationFailed
from diucs.domain.rules.tenant_lifecycle import offboarding_may_complete_at, start_offboarding

CONFIRM_MESSAGE: Final = "must be the id of the tenant to offboard"


@dataclass(frozen=True, slots=True)
class StartOffboardingCommand:
    actor: Actor
    confirm_tenant_id: str
    """The tenant's id, typed by the operator: starting an offboarding is deliberate."""


@dataclass(frozen=True, slots=True)
class StartOffboardingResult:
    tenant_id: str
    started_at: datetime
    notice_ends_at: datetime


class StartTenantOffboarding(OperatorUseCase):
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

    async def execute(self, command: StartOffboardingCommand) -> StartOffboardingResult:
        _, scope = self._begin(command.actor)
        if type(command.confirm_tenant_id) is not str or command.confirm_tenant_id != scope.value:
            raise ValidationFailed("confirm_tenant_id", CONFIRM_MESSAGE)
        tenant = await self._tenants.get(scope.value)
        if tenant is None:
            raise NotFound(NO_TENANT)
        now = self._clock.now()
        # Only an active or suspended tenant moves (`InvalidTransition` otherwise, nothing written).
        started = start_offboarding(tenant, now)
        if not await self._registry.save(
            started, expected_epoch=tenant.epoch, expected_status=tenant.status
        ):
            raise Conflict(MOVED)
        for changed in self._on_changed:
            changed(scope.value)
        notice_ends_at = offboarding_may_complete_at(started)
        async with self._uow_factory() as uow:
            _unit_scope(uow)
            await _audit(
                uow,
                self._clock,
                command.actor,
                "StartTenantOffboarding",
                AUDIT_UPDATE,
                f"tenant-{scope.value}",
                {
                    "from": tenant.status.value,
                    "noticeEndsAt": notice_ends_at.isoformat(),
                    "epoch": started.epoch,
                },
            )
            await uow.commit()
        return StartOffboardingResult(
            tenant_id=scope.value, started_at=now, notice_ends_at=notice_ends_at
        )
