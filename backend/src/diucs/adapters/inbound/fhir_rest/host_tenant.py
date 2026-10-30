"""Tenant resolution from the request host, for every route that carries no token (TEN-040,
DEC-134 item 3, DEC-167 item 1).

One sub-domain per tenant. `bind_host_tenant` is the dependency of an unauthenticated route: it asks
the tenant directory who owns the host (an active tenant only, `resolve_active_tenant`), binds that
tenant for the request, and leaves nothing bound when the request ends. The host is the `Host`
header, port and final dot removed, in lower case. No other header (`X-Forwarded-Host`,
`Forwarded`, `X-Tenant`), no query string, cookie or body is read for a tenant: a proxy must pass
the original `Host` on, and nothing the caller adds can name another tenant.

Every way of not resolving answers the same: a host that is not a host name, a host no tenant
owns, a tenant that is not active and a damaged record all raise `HostNotResolved`, a `NotFound`, so
the route is not run and the answer is the one for a resource that is not there. The dependency is
async, so it runs in the request's own task and the binding reaches the route (lesson L151).
"""

from collections.abc import AsyncIterator

from fastapi import Request

from diucs.adapters.inbound.fhir_rest.app import get_container
from diucs.application.edge_tenant import resolve_active_tenant
from diucs.application.ports.outbound.tenants import normalise_host
from diucs.application.tenancy import bind_tenant
from diucs.domain.errors import NotFound
from diucs.domain.model.tenant import Tenant


class HostNotResolved(NotFound):
    """No active tenant owns this host. The answer is the one for a missing resource."""


def request_host(request: Request) -> str | None:
    """The host the request was addressed to: the Host header without its port, or None when there
    is none or it is not a host name. Only the Host header is read."""
    raw = request.headers.get("host")
    if raw is None:
        return None
    name = raw.rsplit(":", 1)[0] if ":" in raw else raw
    return normalise_host(name)


async def resolve_request_tenant(request: Request) -> Tenant | None:
    """The active tenant the request host names, or None."""
    container = get_container(request)
    return await resolve_active_tenant(container.tenants, request_host(request))


async def bind_host_tenant(request: Request) -> AsyncIterator[Tenant]:
    tenant = await resolve_request_tenant(request)
    if tenant is None:
        raise HostNotResolved
    with bind_tenant(tenant.id):
        yield tenant
