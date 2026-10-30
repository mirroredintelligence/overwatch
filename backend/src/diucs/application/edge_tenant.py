"""The tenant a host names, for every route that carries no token (TEN-040, DEC-134 item 3,
DEC-167 item 1).

One tenant per sub-domain: the host is looked up in the tenant directory (global, read-only, the
only code that runs before a scope is bound) and nothing else is read for a tenant: no header, no
query, no body. The host only chooses where to look. Whatever the route then reads is read inside
the tenant it bound, so a forged host can do no more than name another tenant's scope, where a key
it does not hold finds nothing.

Fail closed: a host that is not a host name is not looked up, and a host no tenant owns, a tenant
that is not active (provisioning, suspended, offboarding, offboarded, purged) and a record the
directory refuses all give None. The caller answers every None the same way, so an unknown host
cannot be told from a suspended tenant's. Only a damaged record is logged, as a reason word.
"""

import logging

from diucs.application.ports.outbound.tenants import (
    TenantDirectory,
    TenantRecordInvalid,
    normalise_host,
)
from diucs.domain.model.tenant import Tenant, TenantStatus

log = logging.getLogger(__name__)


async def resolve_active_tenant(directory: TenantDirectory, host: str | None) -> Tenant | None:
    """The active tenant that owns this host, or None. Any other failure of the directory is
    raised: a route with no tenant must not open because the directory was down."""
    name = normalise_host(host)
    if name is None:
        return None
    try:
        tenant = await directory.by_host(name)
    except TenantRecordInvalid:
        log.warning("host refused: reason=tenant-record")
        return None
    if type(tenant) is not Tenant or tenant.status is not TenantStatus.ACTIVE:
        return None
    return tenant
