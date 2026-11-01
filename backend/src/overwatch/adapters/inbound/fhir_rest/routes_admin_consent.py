"""The return of an administrator from Microsoft's admin consent page (DEC-1316 item 5).

`POST /admin-consent/confirmation` body `{state, adminConsent}`. Public: no token and no
session, and no host that names a tenant (the person is returned to the platform's own host). It is
called by the front end's return page, never by a browser of the administrator directly.

THE TENANT. The state is `<tenant id>.<random>`. The tenant id in it is only a routing hint: the
route binds that tenant, and the use case finds the invite by the hash of the whole state inside it.
A state that names the wrong tenant, a made-up state, a replaced invite and a state of another
tenant all answer the same 404. Nothing but the state is read, and `adminConsent` (what Microsoft's
redirect said) is never taken as proof: the use case asks Microsoft Graph in the administrator's
directory whether our app is installed there.

Limits: the source-address limit of the public routes comes first. Every answer is `no-store`.
"""

from typing import Any, Final

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from overwatch.adapters.inbound.fhir_rest.routes_public import public_rate_limit
from overwatch.application.tenancy import bind_tenant
from overwatch.application.use_cases.admin_consent import ConfirmAdminConsent
from overwatch.domain.errors import NotFound
from overwatch.domain.rules.admin_consent import tenant_hint

PATH: Final = "/admin-consent/confirmation"
_HEADERS: Final = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}

router = APIRouter()


class ConfirmationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: str = Field(min_length=1, max_length=128)
    adminConsent: bool | None = None


def _confirm_service(request: Request) -> ConfirmAdminConsent:
    service: ConfirmAdminConsent | None = getattr(request.app.state, "admin_consent_confirm", None)
    if service is None:
        raise RuntimeError("the admin consent confirmation is not configured")
    return service


@router.post(PATH, dependencies=[Depends(public_rate_limit)])
async def confirm_admin_consent(body: ConfirmationBody, request: Request) -> Response:
    service = _confirm_service(request)
    hint = tenant_hint(body.state)
    if hint is None:
        raise NotFound("no such invitation")
    with bind_tenant(hint):
        result = await service.execute(body.state, admin_consent=body.adminConsent)
    payload: dict[str, Any] = {
        "status": result.status.value,
        "reason": result.reason,
        "organisation": result.organisation,
    }
    return JSONResponse(payload, headers=_HEADERS)
