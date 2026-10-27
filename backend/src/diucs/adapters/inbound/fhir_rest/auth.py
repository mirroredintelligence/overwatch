"""Authentication, roles and service scope for the FHIR API (R02).

Every FHIR call carries `Authorization: Bearer <JWT>` from the BFF. `current_actor` checks the token
and turns it into an Actor. `require_role`, `ensure_can_act_for` and `ensure_patient_access` refuse
with NotAllowed, which the app answers with the same 404 body as a missing record (DEC-086 item 5).
`PROJECTIONS` removes fields a role may not see and labels the result (DEC-098).

The BFF secret is read through `request.app.state.secrets`, a SecretStore set by the process that
serves the app (DEC-096). No secret value is logged, returned or put in an error.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Final, TypeVar

from fastapi import Depends, Request
from fhir.resources.R4B.resource import Resource

from diucs.application.actor import Actor
from diucs.domain.codes import Role
from diucs.domain.rules.bff_token import BffClaims

BFF_SECRET_NAME: Final = "bff-jwt"
PATIENT_ROLES: Final = frozenset({Role.ADVISOR, Role.CLINICAL})

ResourceT = TypeVar("ResourceT", bound=Resource)


def actor_from_claims(claims: BffClaims) -> Actor:
    raise NotImplementedError("actor_from_claims is an R02 red stub")


def current_actor(request: Request) -> Actor:
    raise NotImplementedError("current_actor is an R02 red stub")


def require_role(*roles: Role) -> Callable[[Actor], Awaitable[Actor]]:
    # The factory itself must not fail: routes are registered when a fixture runs, so a stub that
    # raised here would hide every per-test red behind a setup error (lesson L114).
    async def dependency(actor: Annotated[Actor, Depends(current_actor)]) -> Actor:
        raise NotImplementedError("require_role is an R02 red stub")

    return dependency


def ensure_can_act_for(actor: Actor, service_id: str) -> None:
    raise NotImplementedError("ensure_can_act_for is an R02 red stub")


def ensure_patient_access(actor: Actor) -> None:
    raise NotImplementedError("ensure_patient_access is an R02 red stub")


class ProjectionRegistry:
    def register(self, resource_type: str, role: Role, fn: Callable[[Any], Any]) -> None:
        raise NotImplementedError("ProjectionRegistry.register is an R02 red stub")

    def project(self, resource: ResourceT, actor: Actor) -> ResourceT:
        raise NotImplementedError("ProjectionRegistry.project is an R02 red stub")


PROJECTIONS: Final = ProjectionRegistry()
