"""The tenants the workers and the outbox relay serve, plus the one demo tenant (DEC-1320).

The consumers and the relay serve the ACTIVE tenants of the tenant directory, and dead-letter a
message for any other tenant: that check is a control (DEC-165), because the tenant id on a bus
message is unsigned. While the TEMPORARY DEMO switch `OVERWATCH_DEMO_INBOUND_TENANT` names a tenant
that is still being set up, that tenant alone is added to the list, so the demo can answer before
go-live. Nothing else changes: no other tenant, no other state (a suspended, closing or closed
tenant is never added), and with the switch unset the list is the directory's, exactly.
"""

from collections.abc import Sequence
from typing import Protocol

from overwatch.domain.model.tenant import Tenant, TenantStatus


class _Directory(Protocol):
    async def active_tenant_ids(self) -> Sequence[str]: ...

    async def get(self, tenant_id: str) -> Tenant | None: ...


class DemoAwareTenants:
    """`active_tenant_ids` of the directory, and the demo tenant when it is in provisioning."""

    def __init__(self, directory: _Directory, demo_tenant: str | None) -> None:
        self._directory = directory
        self._demo = demo_tenant

    async def active_tenant_ids(self) -> Sequence[str]:
        ids = list(await self._directory.active_tenant_ids())
        demo = self._demo
        if demo is None or demo in ids:
            return ids
        tenant = await self._directory.get(demo)
        if tenant is not None and tenant.status is TenantStatus.PROVISIONING:
            ids.append(demo)
        return ids
