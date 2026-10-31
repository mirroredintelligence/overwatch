"""The synthetic test hook (O09, TEN-G04): POST /test/synthetic/prompt.

The synthetic checks (frontend/e2e/synthetic) call this hook to issue a fresh capacity link for the
synthetic test service, so a reporter loop can run end to end on a deployed environment without a
real person or number. It is the one route in the product that issues a link on request, so it
refuses everything unless all three hold:

- the hook is configured and switched on (`synthetic_enabled`, DIUCS_SYNTHETIC_ENABLED), and
- the bearer equals the hook token, compared in constant time, and
- the tenant is the one configured at the edge. A request never names a tenant: a tenant in the
  body or the query is ignored.

Every refusal is the same 404 with the same body, so the route does not show whether it is
configured, switched on or what the token looks like. Nothing here logs the token or the link.
"""

import hmac
from dataclasses import dataclass, field
from typing import Protocol

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from diucs.application.tenancy import bind_tenant, is_valid_tenant_id

router = APIRouter(prefix="/test/synthetic")
_REFUSED_BODY = {"error": "not found"}
_BEARER = "bearer"


class SyntheticLinkIssuer(Protocol):
    async def issue(self) -> str:
        """Issue a fresh capacity link for the synthetic test service; return the link."""
        ...


@dataclass(frozen=True, slots=True)
class SyntheticHook:
    enabled: bool
    # Never shown: a repr of the hook does not print the token.
    token: str | None = field(repr=False)
    tenant_id: str
    issuer: SyntheticLinkIssuer = field(repr=False)

    def __post_init__(self) -> None:
        if not is_valid_tenant_id(self.tenant_id):
            raise ValueError("the synthetic tenant id is not a valid tenant id")

    def admits(self, authorization: str | None) -> bool:
        """True only when the hook is on, a token is set, and the header is `Bearer <token>` with
        exactly that token."""
        if not self.enabled or not self.token:
            return False
        scheme, _, given = (authorization or "").partition(" ")
        if scheme.lower() != _BEARER:
            return False
        return hmac.compare_digest(given.encode("utf-8"), self.token.encode("utf-8"))


def _refused() -> JSONResponse:
    return JSONResponse(_REFUSED_BODY, status_code=404)


@router.post("/prompt", status_code=201)
async def post_prompt(request: Request) -> JSONResponse:
    hook = request.app.state.synthetic
    if not isinstance(hook, SyntheticHook) or not hook.admits(request.headers.get("authorization")):
        return _refused()
    # The tenant is bound here, from the configured hook, and nothing the request sent is read.
    with bind_tenant(hook.tenant_id):
        link = await hook.issuer.issue()
    return JSONResponse({"link": link}, status_code=201)
