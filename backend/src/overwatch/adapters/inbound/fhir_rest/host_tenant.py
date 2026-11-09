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

from overwatch.adapters.inbound.fhir_rest.app import get_container
from overwatch.application.edge_tenant import (
    resolve_active_tenant,
    resolve_hinted_tenant,
    resolve_sign_in_tenant,
)
from overwatch.application.ports.outbound.tenants import normalise_host
from overwatch.application.tenancy import bind_tenant
from overwatch.domain.errors import NotFound
from overwatch.domain.model.tenant import Tenant


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


async def bind_sign_in_tenant(request: Request) -> AsyncIterator[Tenant]:
    """As `bind_host_tenant`, for the staff sign-in only: a tenant still being set up is let
    through, and the token it gets is limited to the tenant administrator (DEC-1321)."""
    tenant = await resolve_sign_in_tenant(get_container(request).tenants, request_host(request))
    if tenant is None:
        raise HostNotResolved
    with bind_tenant(tenant.id):
        yield tenant


def request_hint(request: Request) -> str | None:
    """The tenant id the trusted edge named for this request (DEC-1354), or None. The edge
    middleware sets it only for a request it trusts and removes the header from every request."""
    found = getattr(request.state, "tenant_hint", None)
    return found if isinstance(found, str) else None


async def resolve_pre_session_tenant(request: Request) -> Tenant | None:
    """The active tenant of a request with no login: the one the edge named, else the host's."""
    container = get_container(request)
    return await resolve_hinted_tenant(
        container.tenants, request_host(request), request_hint(request)
    )


async def bind_pre_session_tenant(request: Request) -> AsyncIterator[Tenant]:
    """As `bind_host_tenant`, for the routes a person reaches before a session and with no link
    token in hand (a reporter's phone after set-up, a wall screen): the tenant the edge named, else
    the host's (DEC-1354). The routes then look up a secret inside it."""
    tenant = await resolve_pre_session_tenant(request)
    if tenant is None:
        raise HostNotResolved
    with bind_tenant(tenant.id):
        yield tenant


async def bind_host_tenant(request: Request) -> AsyncIterator[Tenant]:
    tenant = await resolve_request_tenant(request)
    if tenant is None:
        raise HostNotResolved
    with bind_tenant(tenant.id):
        yield tenant
