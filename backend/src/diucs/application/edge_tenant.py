"""The tenant a host names, for every route that has no token (TEN-040). Stub for the red commit."""

from diucs.application.ports.outbound.tenants import TenantDirectory
from diucs.domain.model.tenant import Tenant


async def resolve_active_tenant(directory: TenantDirectory, host: str | None) -> Tenant | None:
    raise NotImplementedError
