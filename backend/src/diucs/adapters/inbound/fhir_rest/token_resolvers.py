"""The device-token dependency of routes that carry no signed token (TEN-041, DEC-520).

A wall screen holds an opaque device token (DEC-224) and presents it as `Authorization: Bearer`.
`resolve_active_device` binds the tenant of the request HOST (the one binder, `bind_host_tenant`,
TEN-040) and then looks the token up inside that tenant (`PreSessionResolver`), so the host and the
token cannot disagree: a token of another tenant is not found. Every way of not resolving is the
one 404 of a path that is not there, byte for byte: a host nobody owns, a tenant that is not active,
a missing or malformed header, an unknown token, another tenant's token, a revoked screen. Nothing
but the host names a tenant, and no token reaches a log line or an error.

The dependency is async, so it runs in the request's own task and the binding it makes reaches the
route (lesson L151); the binder restores the previous binding when the request ends.
"""

from typing import Annotated, Any, Protocol, cast

from fastapi import Depends, Request

from diucs.adapters.inbound.fhir_rest.host_tenant import bind_host_tenant
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.tokens import SecretStore
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenant_resolution import EntryRefused, PreSessionResolver
from diucs.domain.model.device import Device
from diucs.domain.model.tenant import Tenant


class _Container(Protocol):
    @property
    def clock(self) -> Clock: ...

    @property
    def uow_factory(self) -> UnitOfWorkFactory: ...

    @property
    def secrets(self) -> SecretStore: ...


def pre_session_resolver(request: Request) -> PreSessionResolver:
    """The resolver over the container's unit of work, clock and tenant-keyed secrets. A container
    that lacks one is a configuration fault: the 500 of any other, never an open route."""
    container = cast(_Container, request.app.state.container)
    return PreSessionResolver(container.uow_factory, container.clock, container.secrets)


def bearer_token(request: Request) -> str:
    """The token after the `Bearer` scheme, or `EntryRefused`. One token only: a header with a
    space inside the token, no token, or another scheme is refused, with no hint of which."""
    header: Any = request.headers.get("authorization")
    if not isinstance(header, str):
        raise EntryRefused
    scheme, _, rest = header.partition(" ")
    token = rest.strip()
    if scheme.lower() != "bearer" or not token or " " in token:
        raise EntryRefused
    return token


async def resolve_active_device(
    request: Request, tenant: Annotated[Tenant, Depends(bind_host_tenant)]
) -> Device:
    """The active wall screen the bearer token belongs to, inside the host's tenant."""
    return await pre_session_resolver(request).device(bearer_token(request))
