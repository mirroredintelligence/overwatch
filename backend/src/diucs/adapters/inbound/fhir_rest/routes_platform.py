"""The platform's routes: the operator console's back end and the support person's side of a ticket
(TEN-075, TEN-043, TEN-084, DEC-134 items 4 and 5, DEC-136 items 6 and 10).

Not FHIR (a tenant is not a FHIR resource): plain JSON under `/platform`, never cached
(`Cache-Control: no-store`), errors as the rest of the API's OperationOutcome. The mount is the app
root, not `/fhir`.

THE DOOR. Every route takes an OPERATOR token (audience `diucs-ops`, issued by
`/auth/operator-token` from the operator's own directory, TEN-043): a tenant token is a 401 here and
an operator token is a 401 on every tenant route. The role then decides, and a role that may not
use a route reads it as the 404 of a route that is not there:

  GET    /platform/session                              operator, support
  GET    /platform/tenants                              operator (full), support (id, name, status)
  PUT    /platform/tenants/{id}                         operator: create (idempotent)
  GET    /platform/tenants/{id}                         operator: the detail and its blockers
  PUT    /platform/tenants/{id}/host                    operator
  POST   /platform/tenants/{id}/numbers                 operator: record the tenant's text number
  POST   /platform/tenants/{id}/numbers/tested          operator: a test text was delivered
  PUT    /platform/tenants/{id}/references              operator: DSA, DPIA and DCB0160 references
  POST   /platform/tenants/{id}/directory/verification  operator: verify the bound directory
  POST   /platform/tenants/{id}/admin-invitation        operator: invite the first administrator
  POST   /platform/tenants/{id}/activation              operator
  POST   /platform/tenants/{id}/suspension              operator (mode and reason)
  DELETE /platform/tenants/{id}/suspension              operator: resume
  POST   /platform/tenants/{id}/offboarding             operator: start (typed tenant id)
  GET    /platform/audit, /platform/audit/verification  operator: the platform's own chain
  POST   /platform/tenants/{id}/support-tickets         support: ask for access, with a reason
  GET    /platform/support-tickets[/{ticket}]           support: their own tickets
  POST   /platform/support-tickets/{ticket}/cancellation  support
  POST   /platform/support-tickets/{ticket}/access      support: open with the code
  DELETE /platform/support-tickets/{ticket}/access      support: end it

THE TENANT. An operator names a tenant in the path of an operator-only route, and the tenant is
bound for that request alone, after the token and the role are checked (`operator_in_tenant`): the
operator's token names no tenant, so the path is the target of the act, never a source of authority.
The operator has no data access: what its use cases touch in a tenant is the tenant's structure and
its audit chain. A support person names the tenant of a ticket in the path too; the guard (the one
binder of a tenant a platform principal names) checks the principal and the tenant before it binds
anything. No body carries a tenant.

WRITES. An `Idempotency-Key` is required on every write. An operator write is replayed from the
24-hour cache like the tenant routes' (the cache is tenant-qualified, so the key is the operator's
in that tenant). A support write is not cached (there is no tenant to qualify the key with, and a
ticket's own state is what makes a repeat harmless: a second request is a conflict, a second
cancellation an invalid move, a second opening a refused code).

AUDIT. Every lifecycle step the operator takes is written to the platform chain after it is done
(`PlatformRecorder`); the answer says `recorded: false` when the chain could not be written, so the
console can say the step was done and not recorded. The tenant's own chain already holds the step.

The services are on `app.state.platform_services` (set by the process that serves the app); with
none, every route fails closed with a 500.
"""

from datetime import UTC, datetime
from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from diucs.adapters.inbound.fhir_rest.auth import operator_in_tenant, require_operator
from diucs.adapters.inbound.fhir_rest.concurrency import idempotency_key, replay_or_run
from diucs.adapters.inbound.fhir_rest.errors import operation_outcome
from diucs.application.actor import Actor
from diucs.application.cross_tenant_guard import PlatformPrincipal
from diucs.application.platform_services import PlatformServices
from diucs.application.ports.outbound.platform_audit import PlatformAuditRecord
from diucs.application.ports.outbound.tenant_registry import RegistryTenant
from diucs.application.use_cases.cross_tenant_tickets import (
    CancelTicketCommand,
    OpenTicketCommand,
    RequestTicketCommand,
    TicketView,
)
from diucs.application.use_cases.platform_tenants import PlatformTenantDetail
from diucs.application.use_cases.tenant_access import InviteTenantAdminCommand
from diucs.application.use_cases.tenant_admin import (
    ActivateTenantCommand,
    CreateTenantCommand,
    MarkNumberTestedCommand,
    RecordNumberCommand,
    RecordReferencesCommand,
    SetHostCommand,
    VerifyDirectoryCommand,
)
from diucs.application.use_cases.tenant_offboarding import StartOffboardingCommand
from diucs.application.use_cases.tenant_suspend import ResumeTenantCommand, SuspendTenantCommand
from diucs.domain.codes import Role
from diucs.domain.model.tenant import OrganisationType, SuspendMode, SuspendReason, Tenant
from diucs.domain.rules.bff_token import OperatorClaims
from diucs.domain.rules.support_ticket import ReasonCode

router = APIRouter(prefix="/platform")

NO_STORE: Final = {"Cache-Control": "no-store"}
TICKET_ID: Final = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"
OPERATOR_ONLY: Final = (Role.PLATFORM_OPERATOR,)
SUPPORT_ONLY: Final = (Role.SUPPORT,)
OPERATOR_OR_SUPPORT: Final = (Role.PLATFORM_OPERATOR, Role.SUPPORT)
AUDIT_PAGE: Final = 50

PERMISSIONS: Final = {
    Role.PLATFORM_OPERATOR: (
        "tenants:list",
        "tenants:read",
        "tenants:provision",
        "tenants:lifecycle",
        "audit:read",
    ),
    Role.SUPPORT: ("tenants:list", "support:request"),
}

Operator = Annotated[OperatorClaims, Depends(require_operator(*OPERATOR_ONLY))]
Support = Annotated[OperatorClaims, Depends(require_operator(*SUPPORT_ONLY))]
AnyOperator = Annotated[OperatorClaims, Depends(require_operator(*OPERATOR_OR_SUPPORT))]
InTenant = Annotated[Actor, Depends(operator_in_tenant)]
# A path that is not a tenant id is refused by the use case or the binder as a route that is not
# there (404), never a 400 that says what a tenant id looks like.
TenantPath = Annotated[str, Path(max_length=64)]
TicketPath = Annotated[str, Path(pattern=TICKET_ID)]


# ---------------------------------------------------------------- bodies


class _Body(BaseModel):
    """A body that names anything it is not for is a bad request. None names a tenant."""

    model_config = ConfigDict(extra="forbid")


class CreateTenantBody(_Body):
    displayName: str = Field(min_length=1, max_length=120)
    legalName: str = Field(min_length=1, max_length=200)
    organisationType: OrganisationType
    countryCode: str = Field(default="GB", min_length=2, max_length=2)
    timeZone: str = Field(default="Europe/London", max_length=64)
    odsCode: str | None = Field(default=None, max_length=16)


class HostBody(_Body):
    host: str = Field(min_length=1, max_length=253)


class NumberBody(_Body):
    e164: str = Field(min_length=1, max_length=20)
    accountSid: str = Field(min_length=1, max_length=40)
    senderLabel: str = Field(min_length=1, max_length=40)


class TestedBody(_Body):
    e164: str = Field(min_length=1, max_length=20)


class ReferencesBody(_Body):
    dsaRef: str | None = Field(default=None, max_length=80)
    dpiaRef: str | None = Field(default=None, max_length=80)
    dcb0160Ref: str | None = Field(default=None, max_length=80)


class DirectoryBody(_Body):
    directoryId: str = Field(min_length=1, max_length=64)


class InvitationBody(_Body):
    mobile: str = Field(min_length=1, max_length=32)


class SuspendBody(_Body):
    mode: SuspendMode
    reason: SuspendReason


class OffboardBody(_Body):
    confirmTenantId: str = Field(min_length=1, max_length=64)


class TicketBody(_Body):
    reasonCode: ReasonCode
    reason: str = Field(min_length=1, max_length=400)
    reference: str | None = Field(default=None, max_length=64)


class OpenBody(_Body):
    code: str = Field(min_length=1, max_length=32)


# ---------------------------------------------------------------- helpers


def _services(request: Request) -> PlatformServices:
    # Fail closed: a missing wiring is a configuration error (a 500), never an empty answer.
    services: PlatformServices | None = getattr(request.app.state, "platform_services", None)
    if services is None:
        raise RuntimeError("no platform services are configured for the platform routes")
    return services


def _json(status: int, body: Any) -> Response:
    return JSONResponse(body, status_code=status, headers=NO_STORE)


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _principal(claims: OperatorClaims) -> PlatformPrincipal:
    return PlatformPrincipal.from_claims(claims)


def tenant_to_dict(tenant: Tenant) -> dict[str, Any]:
    return {
        "id": tenant.id,
        "displayName": tenant.display_name,
        "legalName": tenant.legal_name,
        "organisationType": tenant.organisation_type.value,
        "countryCode": tenant.country_code,
        "timeZone": tenant.time_zone,
        "odsCode": tenant.ods_code,
        "status": tenant.status.value,
        "epoch": tenant.epoch,
        "createdAt": _iso(tenant.created_at),
        "activatedAt": _iso(tenant.activated_at),
        "suspendedAt": _iso(tenant.suspended_at),
        "suspendMode": None if tenant.suspend_mode is None else tenant.suspend_mode.value,
        "suspendReason": None if tenant.suspend_reason is None else tenant.suspend_reason.value,
        "offboardingStartedAt": _iso(tenant.offboarding_started_at),
        "offboardedAt": _iso(tenant.offboarded_at),
        "purgedAt": _iso(tenant.purged_at),
        "references": {
            "dsa": tenant.dsa_ref,
            "dpia": tenant.dpia_ref,
            "dcb0160": tenant.dcb0160_ref,
        },
    }


def listed_to_dict(item: RegistryTenant, role: Role) -> dict[str, Any]:
    """The list row: a support person sees enough to name the tenant of a ticket and no more."""
    tenant = item.tenant
    row: dict[str, Any] = {
        "id": tenant.id,
        "displayName": tenant.display_name,
        "status": tenant.status.value,
    }
    if role is Role.PLATFORM_OPERATOR:
        row |= {
            "organisationType": tenant.organisation_type.value,
            "host": item.host,
            "activatedAt": _iso(tenant.activated_at),
        }
    return row


def detail_to_dict(detail: PlatformTenantDetail) -> dict[str, Any]:
    """One tenant as the operator sees it. A number is the tenant's business line (the number and
    the Twilio account); the reference of its auth token is not shown, only that there is one."""
    activation = detail.activation
    return {
        "tenant": tenant_to_dict(detail.tenant.tenant),
        "host": detail.tenant.host,
        "directoryId": detail.tenant.directory_id,
        "numbers": [
            {
                "e164": number.e164,
                "accountSid": number.account_sid,
                "status": number.status.value,
                "testedAt": _iso(number.tested_at),
                "quarantineUntil": _iso(number.quarantine_until),
                "hasSecret": bool(number.secret_ref),
            }
            for number in detail.numbers
        ],
        "activation": (
            None
            if activation is None
            else {"ready": not activation.blockers, "blockers": list(activation.blockers)}
        ),
    }


def support_ticket_to_dict(view: TicketView) -> dict[str, Any]:
    """A ticket as the support person who asked for it sees it: the tenant's administrator who
    decided is not named, and no hash of a code is shown."""
    ticket = view.ticket
    return {
        "id": ticket.id,
        "tenantId": ticket.tenant_id,
        "state": view.state.value,
        "reasonCode": ticket.reason_code.value,
        "reason": ticket.reason,
        "reference": ticket.reference,
        "requestedAt": _iso(ticket.requested_at),
        "validUntil": _iso(ticket.valid_until),
        "decidedAt": _iso(ticket.decided_at),
        "openedAt": _iso(ticket.opened_at),
        "endedAt": _iso(ticket.ended_at),
        "endedBy": None if ticket.ended_by is None else ticket.ended_by.value,
        "accessId": ticket.access_id,
    }


def audit_record_to_dict(record: PlatformAuditRecord) -> dict[str, Any]:
    return {
        "seq": record.seq,
        "action": record.action,
        "principalRef": record.principal_ref,
        "tenantId": record.tenant_id,
        "accessId": record.access_id,
        "snapshot": record.snapshot,
        "at": _iso(record.at),
    }


async def _step(
    services: PlatformServices,
    actor: Actor,
    action: str,
    body: dict[str, Any],
    status: int = 200,
    snapshot: dict[str, Any] | None = None,
) -> Response:
    """Answer a lifecycle step that is done, after writing it to the platform chain."""
    recorded = await services.recorder.record(
        action, str(actor.practitioner_id), actor.tenant_id, snapshot
    )
    return _json(status, {**body, "recorded": recorded})


# ---------------------------------------------------------------- the session and the list


@router.get("/session")
async def read_session(claims: AnyOperator) -> Response:
    """What the operator console's session needs: who is signed in (the opaque account reference,
    never a name), the role, when the token ends and what the role may do, so the console draws
    only what it can use. The token is the session: it holds nothing the back end must remember, so
    signing out is the console dropping it, and a new token is a new exchange."""
    return _json(
        200,
        {
            "role": claims.role.value,
            "accountRef": claims.sub,
            "expiresAt": _iso(claims.expires_at),
            "permissions": list(PERMISSIONS[claims.role]),
        },
    )


@router.get("/tenants")
async def list_tenants(request: Request, claims: AnyOperator) -> Response:
    listed = await _services(request).tenants.execute()
    return _json(200, {"tenants": [listed_to_dict(item, claims.role) for item in listed]})


# ---------------------------------------------------------------- the operator's lifecycle


@router.put("/tenants/{tenant_id}")
async def create_tenant(
    tenant_id: TenantPath, body: CreateTenantBody, request: Request, actor: InTenant
) -> Response:
    """Create the tenant in provisioning, or finish a creation that stopped (the same fields run
    again): 201 when it is new, 200 when it only finished. The id is the path's."""
    key = idempotency_key(request)

    async def run() -> Response:
        services = _services(request)
        result = await services.create.execute(
            CreateTenantCommand(
                actor=actor,
                tenant_id=tenant_id,
                display_name=body.displayName,
                legal_name=body.legalName,
                organisation_type=body.organisationType,
                country_code=body.countryCode,
                time_zone=body.timeZone,
                ods_code=body.odsCode,
            )
        )
        return await _step(
            services,
            actor,
            "tenant-created",
            {"tenantId": result.tenant_id, "created": result.created},
            201 if result.created else 200,
            {"organisationType": body.organisationType.value},
        )

    return await replay_or_run(request, actor, key, run)


@router.get("/tenants/{tenant_id}")
async def read_tenant(tenant_id: TenantPath, request: Request, actor: InTenant) -> Response:
    detail = await _services(request).detail.execute(actor)
    return _json(200, detail_to_dict(detail))


@router.put("/tenants/{tenant_id}/host")
async def set_host(
    tenant_id: TenantPath, body: HostBody, request: Request, actor: InTenant
) -> Response:
    key = idempotency_key(request)

    async def run() -> Response:
        services = _services(request)
        await services.host.execute(SetHostCommand(actor, body.host))
        return await _step(services, actor, "tenant-host-set", {})

    return await replay_or_run(request, actor, key, run)


@router.post("/tenants/{tenant_id}/numbers")
async def record_number(
    tenant_id: TenantPath, body: NumberBody, request: Request, actor: InTenant
) -> Response:
    key = idempotency_key(request)

    async def run() -> Response:
        services = _services(request)
        channel_id = await services.number.execute(
            RecordNumberCommand(actor, body.e164, body.accountSid, body.senderLabel)
        )
        return await _step(
            services, actor, "tenant-number-recorded", {"channelId": channel_id}, 201
        )

    return await replay_or_run(request, actor, key, run)


@router.post("/tenants/{tenant_id}/numbers/tested")
async def number_tested(
    tenant_id: TenantPath, body: TestedBody, request: Request, actor: InTenant
) -> Response:
    key = idempotency_key(request)

    async def run() -> Response:
        services = _services(request)
        await services.tested.execute(MarkNumberTestedCommand(actor, body.e164))
        return await _step(services, actor, "tenant-number-tested", {})

    return await replay_or_run(request, actor, key, run)


@router.put("/tenants/{tenant_id}/references")
async def record_references(
    tenant_id: TenantPath, body: ReferencesBody, request: Request, actor: InTenant
) -> Response:
    key = idempotency_key(request)

    async def run() -> Response:
        services = _services(request)
        recorded = await services.references.execute(
            RecordReferencesCommand(
                actor,
                dsa_ref=body.dsaRef,
                dpia_ref=body.dpiaRef,
                dcb0160_ref=body.dcb0160Ref,
            )
        )
        return await _step(
            services,
            actor,
            "tenant-references-recorded",
            {"recorded": list(recorded)},
            snapshot={"recorded": list(recorded)},
        )

    return await replay_or_run(request, actor, key, run)


@router.post("/tenants/{tenant_id}/directory/verification")
async def verify_directory(
    tenant_id: TenantPath, body: DirectoryBody, request: Request, actor: InTenant
) -> Response:
    key = idempotency_key(request)

    async def run() -> Response:
        services = _services(request)
        await services.directory.execute(VerifyDirectoryCommand(actor, body.directoryId))
        return await _step(services, actor, "tenant-directory-verified", {})

    return await replay_or_run(request, actor, key, run)


@router.post("/tenants/{tenant_id}/admin-invitation")
async def invite_first_administrator(
    tenant_id: TenantPath, body: InvitationBody, request: Request, actor: InTenant
) -> Response:
    """Invite the tenant's first administrator by mobile number. The mobile is hashed and stored in
    the protected contact store, never echoed or audited; the text is queued to go from the tenant's
    own number. Only when it will stop being valid is answered."""
    key = idempotency_key(request)

    async def run() -> Response:
        services = _services(request)
        invited = await services.invite.execute(InviteTenantAdminCommand(actor, body.mobile))
        return await _step(
            services,
            actor,
            "tenant-admin-invited",
            {"expiresAt": _iso(invited.expires_at)},
            201,
        )

    return await replay_or_run(request, actor, key, run)


@router.post("/tenants/{tenant_id}/activation")
async def activate_tenant(tenant_id: TenantPath, request: Request, actor: InTenant) -> Response:
    """Activate a provisioning tenant. What it waits for is in the detail (`activation.blockers`);
    a tenant that is not ready is a 409 that says so in the blockers' fixed words."""
    key = idempotency_key(request)

    async def run() -> Response:
        services = _services(request)
        assessment = await services.activate.assess(actor)
        if assessment.blockers:
            return operation_outcome(
                409,
                "business-rule",
                "Activation is unavailable until: " + "; ".join(assessment.blockers),
                headers=NO_STORE,
            )
        result = await services.activate.execute(ActivateTenantCommand(actor))
        return await _step(
            services,
            actor,
            "tenant-activated",
            {"tenantId": result.tenant_id, "epoch": result.epoch, "seeded": list(result.seeded)},
            snapshot={"epoch": result.epoch},
        )

    return await replay_or_run(request, actor, key, run)


@router.post("/tenants/{tenant_id}/suspension")
async def suspend_tenant(
    tenant_id: TenantPath, body: SuspendBody, request: Request, actor: InTenant
) -> Response:
    key = idempotency_key(request)

    async def run() -> Response:
        services = _services(request)
        result = await services.suspend.execute(SuspendTenantCommand(actor, body.mode, body.reason))
        return await _step(
            services,
            actor,
            "tenant-suspended",
            {"tenantId": result.tenant_id, "epoch": result.epoch, "mode": result.mode.value},
            snapshot={"mode": body.mode.value, "reason": body.reason.value, "epoch": result.epoch},
        )

    return await replay_or_run(request, actor, key, run)


@router.delete("/tenants/{tenant_id}/suspension")
async def resume_tenant(tenant_id: TenantPath, request: Request, actor: InTenant) -> Response:
    key = idempotency_key(request)

    async def run() -> Response:
        services = _services(request)
        result = await services.resume.execute(ResumeTenantCommand(actor))
        return await _step(
            services,
            actor,
            "tenant-resumed",
            {
                "tenantId": result.tenant_id,
                "epoch": result.epoch,
                "servicesPrompted": result.services_prompted,
                "servicesAnnounced": result.services_announced,
                "resumedAgain": result.resumed_again,
            },
            snapshot={"epoch": result.epoch},
        )

    return await replay_or_run(request, actor, key, run)


@router.post("/tenants/{tenant_id}/offboarding")
async def start_offboarding(
    tenant_id: TenantPath, body: OffboardBody, request: Request, actor: InTenant
) -> Response:
    """Start the thirty-day notice period. The operator types the tenant's own id. Export and purge
    are TEN-074's and are not started here."""
    key = idempotency_key(request)

    async def run() -> Response:
        services = _services(request)
        result = await services.offboard.execute(
            StartOffboardingCommand(actor, body.confirmTenantId)
        )
        return await _step(
            services,
            actor,
            "tenant-offboarding-started",
            {
                "tenantId": result.tenant_id,
                "startedAt": _iso(result.started_at),
                "noticeEndsAt": _iso(result.notice_ends_at),
            },
            snapshot={"noticeEndsAt": _iso(result.notice_ends_at)},
        )

    return await replay_or_run(request, actor, key, run)


# ---------------------------------------------------------------- the platform's own chain


@router.get("/audit")
async def read_audit(
    request: Request,
    claims: Operator,
    after_seq: Annotated[int, Query(alias="afterSeq", ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = AUDIT_PAGE,
) -> Response:
    """The platform chain, oldest first, a page after a sequence. `next` is the sequence to ask
    after for the next page, or null at the end."""
    records = await _services(request).audit_reader.entries(after_seq, limit)
    return _json(
        200,
        {
            "entries": [audit_record_to_dict(record) for record in records],
            "next": records[-1].seq if len(records) == limit else None,
        },
    )


@router.get("/audit/verification")
async def verify_audit(request: Request, claims: Operator) -> Response:
    """Walk the whole chain and recompute every hash: whether it is intact."""
    return _json(200, {"intact": await _services(request).audit_reader.verify()})


# ---------------------------------------------------------------- the support person's tickets


@router.post("/tenants/{tenant_id}/support-tickets")
async def request_ticket(
    tenant_id: TenantPath, body: TicketBody, request: Request, claims: Support
) -> Response:
    idempotency_key(request)
    ticket = await _services(request).tickets.request.execute(
        RequestTicketCommand(
            principal=_principal(claims),
            tenant_id=tenant_id,
            reason_code=body.reasonCode,
            reason=body.reason,
            reference=body.reference,
        )
    )
    view = await _services(request).tickets.reading.for_principal(_principal(claims), ticket.id)
    return _json(201, support_ticket_to_dict(view))


@router.get("/support-tickets")
async def list_tickets(request: Request, claims: Support) -> Response:
    views = await _services(request).tickets.listing.for_principal(_principal(claims))
    return _json(200, {"tickets": [support_ticket_to_dict(view) for view in views]})


@router.get("/support-tickets/{ticket_id}")
async def read_ticket(ticket_id: TicketPath, request: Request, claims: Support) -> Response:
    view = await _services(request).tickets.reading.for_principal(_principal(claims), ticket_id)
    return _json(200, support_ticket_to_dict(view))


@router.post("/support-tickets/{ticket_id}/cancellation")
async def cancel_ticket(ticket_id: TicketPath, request: Request, claims: Support) -> Response:
    idempotency_key(request)
    services = _services(request)
    principal = _principal(claims)
    await services.tickets.cancelling.execute(CancelTicketCommand(principal, ticket_id))
    return _json(
        200,
        support_ticket_to_dict(await services.tickets.reading.for_principal(principal, ticket_id)),
    )


@router.post("/support-tickets/{ticket_id}/access")
async def open_ticket_access(
    ticket_id: TicketPath, body: OpenBody, request: Request, claims: Support
) -> Response:
    """Open the access with the code the tenant's administrator gave. One tenant and an hour; the
    code opens once. Every refusal (not your ticket, not approved, a wrong, used or lapsed code) is
    the one 404."""
    idempotency_key(request)
    services = _services(request)
    principal = _principal(claims)
    opened = await services.tickets.opening.execute(
        OpenTicketCommand(principal, ticket_id, body.code)
    )
    view = await services.tickets.reading.for_principal(principal, ticket_id)
    return _json(
        200,
        {
            "ticket": support_ticket_to_dict(view),
            "access": {
                "accessId": opened.elevation.access_id,
                "tenantId": opened.elevation.tenant_id,
                "expiresAt": _iso(opened.elevation.expires_at),
            },
        },
    )


@router.delete("/support-tickets/{ticket_id}/access")
async def end_ticket_access(ticket_id: TicketPath, request: Request, claims: Support) -> Response:
    idempotency_key(request)
    services = _services(request)
    principal = _principal(claims)
    await services.tickets.ending.execute(CancelTicketCommand(principal, ticket_id))
    return _json(
        200,
        support_ticket_to_dict(await services.tickets.reading.for_principal(principal, ticket_id)),
    )
