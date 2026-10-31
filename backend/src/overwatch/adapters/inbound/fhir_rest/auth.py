"""Authentication, roles, tenant and service scope for the FHIR API (R02, TEN-018).

Every FHIR call carries `Authorization: Bearer <JWT>` from the BFF. `current_actor` checks the
token, checks the tenant it names against the tenant directory (active, and the token's epoch not
behind the record's: `tenant_gate.py`), binds that tenant for the request and turns the claims into
an Actor.
The tenant is the signed claim and nothing else: no header, query, body, cookie or host is read for
it (DEC-130 item 6). Every refusal, whatever the cause, is the same 401. `require_role`,
`ensure_can_act_for` and `ensure_patient_access` refuse with NotAllowed, which the app answers with
the same 404 body as a missing record (DEC-086 item 5). `PROJECTIONS` removes fields a role may not
see and labels the result (DEC-098).

`current_actor` is an async generator dependency: it binds in the request's own task (a plain `def`
dependency would run in a thread pool and its binding would be lost), the handler runs inside the
binding whether it is async or a `def` run in a thread pool (a copy of the context goes with the
call), and the binding is reset when the request ends. A route that does not depend on it, and binds
no tenant itself, is on the reviewed list in `test_edge_binding.py`.

The BFF secret is read through `request.app.state.secrets`, a SecretStore set by the process that
serves the app (DEC-096). No token or secret value is logged, returned or put in an error.
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import timedelta
from typing import Annotated, Any, Final

from fastapi import Depends, HTTPException, Path, Request
from fhir.resources.R4B.coding import Coding
from fhir.resources.R4B.meta import Meta
from fhir.resources.R4B.resource import Resource
from fhir.resources.R4B.task import Task

from diucs.adapters.inbound.fhir_rest.app import get_container
from diucs.adapters.inbound.fhir_rest.tenant_gate import TenantGate
from diucs.application.actor import Actor
from diucs.application.ports.outbound.tokens import SecretStore
from diucs.application.tenancy import ScopeId, bind_scope
from diucs.domain.codes import Role
from diucs.domain.errors import NotAllowed, NotFound, ValidationFailed
from diucs.domain.model.tenant import check_tenant_id
from diucs.domain.rules.bff_token import (
    BffClaims,
    OperatorClaims,
    TokenRejected,
    decode_bff_token,
    decode_operator_token,
)
from diucs.domain.rules.edge_access import EdgeVerdict

BFF_SECRET_NAME: Final = "bff-jwt"
SCREEN_SEEN_EVERY: Final = timedelta(seconds=30)
"""A wall screen's last seen time is written at most this often, however often it reads."""
PATIENT_ROLES: Final = frozenset({Role.ADVISOR, Role.CLINICAL})
_SERVICE_WIDE_ROLES: Final = frozenset({Role.LEAD, Role.ADVISOR, Role.CLINICAL, Role.AUDIT})
REDACTED_SYSTEM: Final = "http://terminology.hl7.org/CodeSystem/v3-ObservationValue"
REDACTED_CODE: Final = "REDACTED"

Projection = Callable[[Any], Any]


def actor_from_claims(claims: BffClaims) -> Actor:
    # A wall screen is a device: its `sub` is the device id and it has no practitioner.
    if claims.role is Role.WALL:
        return Actor(
            role=Role.WALL,
            practitioner_id=None,
            device_id=claims.sub,
            channel="api",
            service_ids=claims.services,
            tenant_id=claims.tenant,
            network_ids=claims.networks,
        )
    return Actor(
        role=claims.role,
        practitioner_id=claims.sub,
        device_id=claims.device,
        channel="api",
        service_ids=claims.services,
        tenant_id=claims.tenant,
        network_ids=claims.networks,
    )


def _unauthorised() -> HTTPException:
    return HTTPException(status_code=401, headers={"WWW-Authenticate": "Bearer"})


def _bearer_token(request: Request) -> str:
    header = request.headers.get("authorization")
    if header is None:
        raise _unauthorised()
    scheme, _, token = header.partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token:
        raise _unauthorised()
    return token


def _secret(request: Request) -> bytes:
    # Fail closed: a missing store or secret is a configuration error (a 500), never a pass.
    store: SecretStore | None = getattr(request.app.state, "secrets", None)
    if store is None:
        raise RuntimeError("no secret store is configured for the FHIR API")
    try:
        return store.get(BFF_SECRET_NAME)
    except NotFound:
        raise RuntimeError("the BFF token secret is not configured") from None


def _gate(request: Request) -> TenantGate:
    # Built on first use and kept on the app, so its record cache lives as long as the app. A
    # directory missing from the container is a configuration error: the 500 of any other.
    gate: TenantGate | None = getattr(request.app.state, "tenant_gate", None)
    if gate is None:
        container = get_container(request)
        gate = TenantGate(container.tenants, container.clock)
        request.app.state.tenant_gate = gate
    return gate


def forget_tenant(app: Any, tenant_id: str) -> None:
    """Make this process judge the next token of the tenant on a fresh read of its record (TEN-073).

    Called after a suspension or a resume, by whatever runs the operator's route in this process
    (`use_cases/tenant_suspend.py`, `on_changed`), so the change is immediate here. It is only a
    shortcut: a record that is cached in another process, or here when nothing called this, is read
    again at most `RECORD_TTL` (60 seconds) later, and an epoch behind the record is refused on the
    first read. An app that has built no gate yet has nothing cached."""
    gate: TenantGate | None = getattr(app.state, "tenant_gate", None)
    if gate is not None:
        gate.forget(tenant_id)


async def current_actor(request: Request) -> AsyncIterator[Actor]:
    token = _bearer_token(request)
    secret = _secret(request)
    now = get_container(request).clock.now()
    try:
        claims = decode_bff_token(token, secret, now)
    except TokenRejected:
        raise _unauthorised() from None
    # The directory is asked only after the signature has been checked, and only about the claim.
    if await _gate(request).verdict(claims, request.method) is not EdgeVerdict.ALLOWED:
        raise _unauthorised()
    with bind_scope(ScopeId.tenant(claims.tenant)):
        yield actor_from_claims(claims)


async def current_operator(request: Request) -> OperatorClaims:
    """The operator or support person an operator-audience token names (TEN-043, TEN-075).

    The operator door is the other audience: only a token for `diucs-ops` signed by this back end
    passes, so a tenant token is refused here and an operator token is refused by `current_actor`.
    The token names no tenant, so none is bound and nothing of a tenant is read. Every refusal is
    the same 401 as the tenant door's."""
    token = _bearer_token(request)
    secret = _secret(request)
    now = get_container(request).clock.now()
    try:
        return decode_operator_token(token, secret, now)
    except TokenRejected:
        raise _unauthorised() from None


def require_operator(*roles: Role) -> Callable[[OperatorClaims], Awaitable[OperatorClaims]]:
    """`current_operator`, and the role must be one of these: another operator role is the
    non-revealing 404 of a route that is not there for it."""
    allowed = frozenset(roles)

    async def dependency(
        claims: Annotated[OperatorClaims, Depends(current_operator)],
    ) -> OperatorClaims:
        if claims.role not in allowed:
            raise NotAllowed("role")
        return claims

    return dependency


def operator_actor(claims: OperatorClaims, tenant_id: str) -> Actor:
    """The platform operator as an actor of the one tenant a route names (no service, no device).
    Built only for the `platform-operator` role: the operator has no standing in any scope but the
    one it acts on, and no data access (DEC-134 item 4)."""
    if claims.role is not Role.PLATFORM_OPERATOR:
        raise NotAllowed("role")
    return Actor(
        role=Role.PLATFORM_OPERATOR,
        practitioner_id=claims.sub,
        device_id=None,
        channel="api",
        service_ids=frozenset(),
        tenant_id=tenant_id,
    )


async def operator_in_tenant(
    tenant_id: Annotated[str, Path(max_length=64)],
    claims: Annotated[OperatorClaims, Depends(require_operator(Role.PLATFORM_OPERATOR))],
) -> AsyncIterator[Actor]:
    """The platform operator, acting on the one tenant the path names (TEN-075).

    The operator's token names no tenant, so the tenant is the target of the act: it comes from the
    path of an operator-only route and is bound for that request alone, after the token and the
    role have been checked (an operator has no data access: what its use cases touch in a tenant is
    the tenant's structure and audit chain). A path that is not a tenant id is the 404 of a route
    that is not there; a tenant the registry does not know is refused by the use case before it
    writes. Binds in the request's own task, like `current_actor`, and is reset when it ends."""
    try:
        check_tenant_id(tenant_id)
    except ValidationFailed:
        raise NotFound("no such tenant") from None
    with bind_scope(ScopeId.tenant(tenant_id)):
        yield operator_actor(claims, tenant_id)


def require_role(*roles: Role) -> Callable[[Request, Actor], Awaitable[Actor]]:
    allowed = frozenset(roles)

    async def dependency(
        request: Request, actor: Annotated[Actor, Depends(current_actor)]
    ) -> Actor:
        if actor.role not in allowed:
            raise NotAllowed("role")
        await ensure_screen_live(request, actor)
        return actor

    return dependency


async def ensure_screen_live(request: Request, actor: Actor) -> None:
    """A wall screen is let through only while its record in the bound tenant is active.

    A wall token lasts an hour (TEN-043), so a screen that a lead has revoked would otherwise read
    until it ran out. The registry is asked on every request a wall may make (`require_role` and
    the reads a wall makes through `current_actor`), so the screen stops with its next request: the
    401 a lapsed token gets, which the BFF turns into the end of the screen's session. The same
    step marks the screen seen for the lead's list (at most once in SCREEN_SEEN_EVERY). A screen
    that is not in the tenant, is waiting for its token or is revoked is refused; every other role
    is not asked.
    A registry that cannot answer fails the request, never lets it through.
    """
    if actor.role is not Role.WALL:
        return
    container = get_container(request)
    if actor.device_id is None:
        raise _unauthorised()
    async with container.uow_factory() as uow:
        live = await uow.devices.confirm_active(
            actor.device_id, container.clock.now(), SCREEN_SEEN_EVERY
        )
        await uow.commit()
    if not live:
        raise _unauthorised()


def ensure_can_act_for(actor: Actor, service_id: str) -> None:
    if actor.role in _SERVICE_WIDE_ROLES or service_id in actor.service_ids:
        return
    raise NotAllowed("service")


def ensure_patient_access(actor: Actor) -> None:
    if actor.role not in PATIENT_ROLES:
        raise NotAllowed("patient")


def _with_redacted_label[T: Resource](resource: T) -> T:
    meta = resource.meta or Meta()
    security = [*(meta.security or []), Coding(system=REDACTED_SYSTEM, code=REDACTED_CODE)]
    return resource.model_copy(update={"meta": meta.model_copy(update={"security": security})})


class ProjectionRegistry:
    """What each role may see of each resource type. A rule returns a changed copy, and a changed
    result is labelled REDACTED. A resource with no rule for the caller's role is returned as it is.
    """

    def __init__(self) -> None:
        self._rules: dict[tuple[str, Role], Projection] = {}

    def register(self, resource_type: str, role: Role, fn: Projection) -> None:
        key = (resource_type, role)
        if key in self._rules:
            raise ValueError(f"a projection for {resource_type} and {role.value} is already set")
        self._rules[key] = fn

    def project[T: Resource](self, resource: T, actor: Actor) -> T:
        rule = self._rules.get((resource.get_resource_type(), actor.role))
        if rule is None:
            return resource
        projected: T = rule(resource)
        if projected == resource:
            return resource
        return _with_redacted_label(projected)


# Outputs of a booking that are the SPOA's own records: the id of the message that asked the
# service, its delivery state, and who acknowledged a withdrawal and when (WB4).
_SPOA_OUTPUTS: Final = frozenset(
    {"request-message", "request-delivery", "acknowledged-by", "acknowledged-at"}
)


def _reporter_task(task: Task) -> Task:
    # The case a booking refers to (focus) and the patient (for) are not a reporter's to see, nor
    # are the SPOA's own records on it. The rule covers every Task, not only bookings: P02 writes no
    # Task.code, so a booking cannot be told apart by code, and failing closed is the safer reading
    # (DEC-098 item 2).
    update: dict[str, Any] = {"focus": None, "for_fhir": None}
    if task.output:
        kept = [
            entry
            for entry in task.output
            if not (
                entry.type is not None
                and entry.type.coding
                and entry.type.coding[0].code in _SPOA_OUTPUTS
            )
        ]
        update["output"] = kept or None
    return task.model_copy(update=update)


PROJECTIONS: Final = ProjectionRegistry()
PROJECTIONS.register("Task", Role.REPORTER, _reporter_task)
