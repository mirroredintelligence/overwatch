"""The platform operator's reads of its tenants: the list and one tenant's detail (TEN-075).

`ListPlatformTenants` is the registry's list, whatever the status: the operator console's first
page, and the support person's way to name the tenant a ticket is for (the route gives a support
person the id, the display name and the status and nothing else). `ReadPlatformTenant` is one
tenant as the operator sees it while provisioning it and afterwards: the record, its host, the
directory bound to it, its numbers (the number and the Twilio account are the tenant's business
line, never a person's; the reference of the auth token is not shown, only that there is one), and,
while the tenant is in provisioning, what activation still waits for (`ActivateTenant.assess`, in
the fixed words of the blockers).

Nothing here reads a tenant's own data: the registry and the activation facts only. The detail runs
for the one tenant the edge bound from the operator's path, as every operator use case does.
"""

from dataclasses import dataclass

from diucs.application.actor import Actor
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.tenant_registry import (
    RegistryTenant,
    TenantNumberRecord,
    TenantRegistry,
)
from diucs.application.ports.outbound.tenants import TenantDirectory
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.tenant_admin import (
    NO_TENANT,
    ActivateTenant,
    ActivationAssessment,
    OperatorUseCase,
)
from diucs.domain.errors import NotFound
from diucs.domain.model.tenant import TenantStatus


class ListPlatformTenants:
    def __init__(self, registry: TenantRegistry) -> None:
        self._registry = registry

    async def execute(self) -> tuple[RegistryTenant, ...]:
        return await self._registry.list_all()


@dataclass(frozen=True, slots=True)
class PlatformTenantDetail:
    tenant: RegistryTenant
    numbers: tuple[TenantNumberRecord, ...]
    activation: ActivationAssessment | None
    """What activation waits for: only while the tenant is in provisioning, else None."""


class ReadPlatformTenant(OperatorUseCase):
    def __init__(
        self,
        tenants: TenantDirectory,
        registry: TenantRegistry,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        activate: ActivateTenant,
    ) -> None:
        super().__init__(tenants, uow_factory, clock)
        self._registry = registry
        self._activate = activate

    async def execute(self, actor: Actor) -> PlatformTenantDetail:
        _, scope = self._begin(actor)
        found = await self._registry.detail(scope.value)
        if found is None:
            raise NotFound(NO_TENANT)
        numbers = await self._registry.numbers(scope.value)
        assessment = (
            await self._activate.assess(actor)
            if found.tenant.status is TenantStatus.PROVISIONING
            else None
        )
        return PlatformTenantDetail(tenant=found, numbers=numbers, activation=assessment)
