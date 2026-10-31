"""Public routes: no token, the tenant is the host (TEN-040, DEC-134 item 3).

`GET /public/tenant-profile` answers the display fields of the tenant the request host names, so a
page can show its organisation's name and wording before anyone signs in (the front end's profile
layer, TEN-049, reads it per host). It is not FHIR.

Order of events: the source-address limit (platform namespace, counted before the host is looked
at, so a flood of unknown hosts costs the same as a flood of known ones), then the host-bound binder
(`bind_host_tenant`), then the read. A host no tenant owns, a tenant that is not active and a
damaged record answer as a resource that is not there. A cache that cannot be reached is a fixed
503, and a container with no platform namespace is a 500: never a route with no limit. Every answer
is `no-store` and varies by host.
"""

import logging
from typing import Annotated, Any, Protocol, cast

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response

from diucs.adapters.inbound.fhir_rest.errors import RateLimited, TemporarilyUnavailable
from diucs.adapters.inbound.fhir_rest.host_tenant import bind_host_tenant
from diucs.application.ports.outbound.cache import PlatformSlots
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.rate_limits import (
    PUBLIC_KIND,
    PUBLIC_REQUESTS_PER_ADDRESS,
    PUBLIC_WINDOW,
    PlatformRateLimiter,
)
from diucs.application.use_cases.public_profile import ReadPublicProfile
from diucs.domain.model.tenant import Tenant

log = logging.getLogger(__name__)

PUBLIC_PREFIX = "/public"
PROFILE_PATH = f"{PUBLIC_PREFIX}/tenant-profile"
RETRY_AFTER_UNAVAILABLE_SECONDS = 30
_HEADERS = {"Cache-Control": "no-store", "Vary": "Host", "X-Content-Type-Options": "nosniff"}

router = APIRouter()


class _Container(Protocol):
    @property
    def uow_factory(self) -> UnitOfWorkFactory: ...


def _slots(request: Request) -> PlatformSlots:
    """Fail closed: a missing platform namespace is a configuration error (a 500), never a route
    with no limit."""
    container: Any = request.app.state.container
    slots: PlatformSlots | None = getattr(container, "platform_slots", None)
    if slots is None:
        raise RuntimeError("the platform limiter is not configured")
    return slots


async def public_rate_limit(request: Request) -> None:
    """Count the request against its source address. Behind a proxy the process must be started so
    that `request.client` is the client's (uvicorn `--proxy-headers`, the proxy trusted), or one
    address is shared (deployment note, as for the link pages)."""
    slots = _slots(request)
    address = request.client.host if request.client is not None else ""
    try:
        slot = await PlatformRateLimiter(slots).take(
            PUBLIC_KIND, address, PUBLIC_REQUESTS_PER_ADDRESS, PUBLIC_WINDOW
        )
    except OSError as error:
        log.error("public limiter cache unavailable: %s", type(error).__name__)
        raise TemporarilyUnavailable(RETRY_AFTER_UNAVAILABLE_SECONDS) from None
    if slot is None:
        raise RateLimited(int(PUBLIC_WINDOW.total_seconds()))


@router.get(PROFILE_PATH, dependencies=[Depends(public_rate_limit)])
async def tenant_profile(
    request: Request, tenant: Annotated[Tenant, Depends(bind_host_tenant)]
) -> Response:
    container = cast(_Container, request.app.state.container)
    profile = await ReadPublicProfile(container.uow_factory).execute(tenant)
    wording = profile.wording
    body = {
        "displayName": profile.display_name,
        "timeZone": profile.time_zone,
        "locale": profile.locale,
        "wording": None
        if wording is None
        else {
            "systemName": wording.system_name,
            "referralSystemName": wording.referral_system_name,
            "coordinationTeamName": wording.coordination_team_name,
        },
        "coordinationPhone": profile.coordination_phone,
    }
    return JSONResponse(body, headers=_HEADERS)
