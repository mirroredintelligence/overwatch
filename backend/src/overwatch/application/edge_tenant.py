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

from overwatch.application.ports.outbound.tenants import (
    TenantDirectory,
    TenantRecordInvalid,
    normalise_host,
)
from overwatch.domain.model.tenant import Tenant, TenantStatus
from overwatch.domain.rules.tokens import split_link_token

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


async def resolve_hinted_tenant(
    directory: TenantDirectory, host: str | None, hint: str | None
) -> Tenant | None:
    """The active tenant a page with no login belongs to (DEC-1354): the one the trusted edge named,
    else the one that owns the host. The hint only says where to look; every route reads inside the
    tenant by a secret it must hold. A hint that names no active tenant is None, and is not
    quietly replaced by the host."""
    if hint is None:
        return await resolve_active_tenant(directory, host)
    try:
        tenant = await directory.get(hint)
    except TenantRecordInvalid:
        log.warning("hint refused: reason=tenant-record")
        return None
    if type(tenant) is not Tenant or tenant.status is not TenantStatus.ACTIVE:
        return None
    return tenant


async def resolve_link_tenant(
    directory: TenantDirectory, host: str | None, token: str, hint: str | None = None
) -> Tenant | None:
    """The active tenant of a public link (DEC-1354). A link names its own tenant in front of the
    token, so one host can serve every tenant and no custom domain is needed; the tenant is then
    only a place to look, and the token is looked up inside it, where another tenant's token finds
    nothing. A link with no tenant in it (one sent before this) falls back to the host, so a tenant
    that has its own domain keeps working. Every failure is None, and the caller answers it as it
    answers an unknown code."""
    tenant_id, _ = split_link_token(token)
    if tenant_id is None:
        return await resolve_hinted_tenant(directory, host, hint)
    try:
        tenant = await directory.get(tenant_id)
    except TenantRecordInvalid:
        log.warning("link refused: reason=tenant-record")
        return None
    if type(tenant) is not Tenant or tenant.status is not TenantStatus.ACTIVE:
        return None
    return tenant


async def resolve_sign_in_tenant(directory: TenantDirectory, host: str | None) -> Tenant | None:
    """The tenant a staff sign-in may be made on: an active tenant, or one still being set up, whose
    administrators finish the set-up (DEC-1321). Which ROLE may then sign in to a tenant in set-up
    is the edge rule's (`edge_verdict`): only the tenant administrator."""
    name = normalise_host(host)
    if name is None:
        return None
    try:
        tenant = await directory.by_host(name)
    except TenantRecordInvalid:
        log.warning("host refused: reason=tenant-record")
        return None
    if type(tenant) is not Tenant or tenant.status not in (
        TenantStatus.ACTIVE,
        TenantStatus.PROVISIONING,
    ):
        return None
    return tenant
