"""Token exchange over HTTP (TEN-043, DEC-522 to DEC-527): the BFF hands the back end the person's
sign-in, and the back end answers with the tenant-bound token it signed itself.

POST /auth/token           {"idToken"}            staff: the host's tenant, the directory's
                                                  binding, the tenant's role mapping
POST /auth/device-token    Authorization: Bearer  a paired wall screen, by its device token
POST /auth/operator-token  {"idToken"}            the operator console: the operator directory only

A 200 is `{token, expiresAt, role}` and nothing else: no tenant, no subject, no epoch. The token is
a bearer secret, so every answer is `no-store`.

None of these routes has a signed token. The staff and device routes take their tenant from the
request HOST and from nothing else (the one binder, `bind_host_tenant`, TEN-040); the operator route
takes none. Order of work: the source-address limit (platform namespace, counted before the host is
looked at, as for the public profile), then the host, then the credential. A body that names
anything but the credential (a tenant, a role, an audience) is a 400 and is never read.

Every refusal of a staff or operator exchange is the one 403 with the one body, whatever the cause
(a credential that does not verify, a directory the tenant has not bound, no mapped group, a tenant
that cannot be signed into, a customer's directory asking for an operator role). A host no tenant
owns, a suspended tenant and every device token that does not resolve are the one 404 of a path that
is not there. A limiter whose cache cannot be reached is a fixed 503 and never lets the request
through. A server with no exchange configuration, no signing secret or no limiter is a 500, never an
open route and never a refusal.

The collaborators are set by the process that serves the app: `app.state.secrets` (the platform
secret store, holding `bff-jwt` and `account-ref`) and `app.state.token_exchange` (`ExchangeDeps`).
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Annotated, Any, Final, Protocol, cast

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from diucs.adapters.inbound.fhir_rest.errors import (
    RateLimited,
    TemporarilyUnavailable,
    operation_outcome,
)
from diucs.adapters.inbound.fhir_rest.host_tenant import bind_host_tenant
from diucs.adapters.inbound.fhir_rest.token_resolvers import resolve_active_device
from diucs.application.ports.outbound.cache import PlatformSlots
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.identity_verifier import IdentityVerifier
from diucs.application.ports.outbound.tokens import SecretStore
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.rate_limits import PlatformRateLimiter
from diucs.application.use_cases.exchange_token import (
    EXCHANGE_REFUSED_MESSAGE,
    MAX_CREDENTIAL_LENGTH,
    ExchangeDeviceCommand,
    ExchangeDeviceToken,
    ExchangeOperatorCommand,
    ExchangeOperatorToken,
    ExchangeRefused,
    ExchangeStaffCommand,
    ExchangeStaffToken,
    IssuedToken,
)
from diucs.domain.model.device import Device
from diucs.domain.model.tenant import Tenant

log = logging.getLogger(__name__)

AUTH_PREFIX: Final = "/auth"
STAFF_PATH: Final = f"{AUTH_PREFIX}/token"
DEVICE_PATH: Final = f"{AUTH_PREFIX}/device-token"
OPERATOR_PATH: Final = f"{AUTH_PREFIX}/operator-token"
FORBIDDEN_TEXT: Final = EXCHANGE_REFUSED_MESSAGE

# [ASSUMED] (domain-rules 7): the exchanges of one address in a minute. Behind the BFF the address
# is the BFF's (or the client's, when the serving process trusts the BFF's forwarded address), and a
# staff exchange happens once a shift, a screen's once an hour, so this is generous for a tenant's
# whole sign-in population and small for a flood.
EXCHANGE_REQUESTS_PER_ADDRESS: Final = 60
EXCHANGE_WINDOW: Final = timedelta(minutes=1)
EXCHANGE_KIND: Final = "exchange"
RETRY_AFTER_UNAVAILABLE_SECONDS: Final = 30
_HEADERS: Final = {
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
    "Vary": "Host",
    "X-Content-Type-Options": "nosniff",
}

router = APIRouter()


@dataclass(frozen=True, slots=True)
class ExchangeDeps:
    """What the exchange routes need besides the container. `operator_directory_id` is the Entra
    directory of the platform operator's staff; None leaves the operator route unconfigured."""

    verifier: IdentityVerifier
    operator_directory_id: str | None


class _Container(Protocol):
    @property
    def clock(self) -> Clock: ...

    @property
    def uow_factory(self) -> UnitOfWorkFactory: ...


class _Body(BaseModel):
    """A body that names anything but what it is for is a bad request and is never read."""

    model_config = ConfigDict(extra="forbid")


class CredentialBody(_Body):
    idToken: str = Field(min_length=1, max_length=MAX_CREDENTIAL_LENGTH)


class EmptyBody(_Body):
    pass


def _container(request: Request) -> _Container:
    return cast(_Container, request.app.state.container)


def _deps(request: Request) -> ExchangeDeps:
    deps: ExchangeDeps | None = getattr(request.app.state, "token_exchange", None)
    if deps is None:
        raise RuntimeError("the token exchange is not configured")
    return deps


def _secrets(request: Request) -> SecretStore:
    store: SecretStore | None = getattr(request.app.state, "secrets", None)
    if store is None:
        raise RuntimeError("no secret store is configured for the token exchange")
    return store


def _slots(request: Request) -> PlatformSlots:
    container: Any = request.app.state.container
    slots: PlatformSlots | None = getattr(container, "platform_slots", None)
    if slots is None:
        raise RuntimeError("the platform limiter is not configured")
    return slots


async def exchange_rate_limit(request: Request) -> None:
    """Count the request against its source address, before anything else is looked at."""
    slots = _slots(request)
    address = request.client.host if request.client is not None else ""
    try:
        slot = await PlatformRateLimiter(slots).take(
            EXCHANGE_KIND, address, EXCHANGE_REQUESTS_PER_ADDRESS, EXCHANGE_WINDOW
        )
    except OSError as error:
        log.error("exchange limiter cache unavailable: %s", type(error).__name__)
        raise TemporarilyUnavailable(RETRY_AFTER_UNAVAILABLE_SECONDS) from None
    if slot is None:
        raise RateLimited(int(EXCHANGE_WINDOW.total_seconds()))


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _issued(issued: IssuedToken) -> Response:
    body = {"token": issued.token, "expiresAt": _iso(issued.expires_at), "role": issued.role.value}
    return JSONResponse(body, headers=_HEADERS)


def _forbidden() -> Response:
    return operation_outcome(403, "forbidden", FORBIDDEN_TEXT, headers=_HEADERS)


@router.post(STAFF_PATH, dependencies=[Depends(exchange_rate_limit)])
async def exchange_staff(
    request: Request, body: CredentialBody, tenant: Annotated[Tenant, Depends(bind_host_tenant)]
) -> Response:
    container = _container(request)
    use_case = ExchangeStaffToken(
        container.uow_factory, container.clock, _deps(request).verifier, _secrets(request)
    )
    try:
        issued = await use_case.execute(
            ExchangeStaffCommand(tenant=tenant, credential=body.idToken)
        )
    except ExchangeRefused:
        return _forbidden()
    return _issued(issued)


class _Resolved:
    """The screen the dependency has already found, handed to the use case so the store is read
    once."""

    def __init__(self, device: Device) -> None:
        self._device = device

    async def device(self, token: str) -> Device:
        return self._device


@router.post(DEVICE_PATH, dependencies=[Depends(exchange_rate_limit)])
async def exchange_device(
    request: Request,
    _body: EmptyBody,
    device: Annotated[Device, Depends(resolve_active_device)],
    tenant: Annotated[Tenant, Depends(bind_host_tenant)],
) -> Response:
    container = _container(request)
    use_case = ExchangeDeviceToken(container.clock, _Resolved(device), _secrets(request))
    issued = await use_case.execute(ExchangeDeviceCommand(tenant=tenant, token=""))
    return _issued(issued)


@router.post(OPERATOR_PATH, dependencies=[Depends(exchange_rate_limit)])
async def exchange_operator(request: Request, body: CredentialBody) -> Response:
    deps = _deps(request)
    if deps.operator_directory_id is None:
        raise RuntimeError("the operator directory is not configured")
    use_case = ExchangeOperatorToken(
        _container(request).clock, deps.verifier, _secrets(request), deps.operator_directory_id
    )
    try:
        issued = await use_case.execute(ExchangeOperatorCommand(credential=body.idToken))
    except ExchangeRefused:
        return _forbidden()
    return _issued(issued)
