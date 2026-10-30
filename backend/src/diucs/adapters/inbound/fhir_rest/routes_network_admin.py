"""The network and grant administration API (TEN-079, DEC-132 items 2 and 3, DEC-136 items 3 and
10, DEC-134 item 4).

JSON outside `/fhir`, never cached (`Cache-Control: no-store`), over the use cases of
`network_admin.py`, `membership.py`, `listing_admission.py` and `grants.py`. Two roles run it, both
bound to their own tenant by the edge (`current_actor`): the `tenant-admin` of an organisation runs
that organisation's side (its memberships, its grants, its listings), and the `network-admin` of the
network's owner runs the sharing of the network (the agreement, the members, the owner's approval
of a grant, the decisions on listings). The route layer holds no rule and reads no tenant, network
membership or role from a body, a query or a header: the token binds the tenant, the registry is
asked on every call (the claim `networks` is not used here), and a record that is not the caller's
is the one 404 of the API, so a network, a grant or a listing of another organisation cannot be
discovered. A role that may not use a route is the same 404 (`require_role`); the platform operator
is refused at the edge.

    GET   /network-admin/networks                     tenant-admin, network-admin
    GET   /network-admin/network/{id}/members         network-admin (the owner)
    POST  /network-admin/network/{id}/members         network-admin: {tenant_id}
    POST  /network-admin/network/{id}/members/{membership}/remove    network-admin
    POST  /network-admin/network/{id}/leave           tenant-admin
    POST  /network-admin/memberships/{membership}/accept
                                tenant-admin: {agreement_version}
    POST  /network-admin/network/{id}/agreement
                                network-admin: {reference, version}
    GET   /network-admin/network/{id}/projection      network-admin (the owner)
    GET   /network-admin/grants                       tenant-admin (its own)
    GET   /network-admin/network/{id}/grants          network-admin (the owner)
    POST  /network-admin/grants
                                tenant-admin: {network_id, scope, effective_from?, effective_to?}
    POST  /network-admin/grants/{id}/approve          tenant-admin or network-admin
    POST  /network-admin/grants/{id}/decline          tenant-admin or network-admin
    POST  /network-admin/grants/{id}/end              tenant-admin (the grantor)
    POST  /network-admin/grants/{id}/revise
                                tenant-admin: {effective_from?, effective_to?}
    GET   /network-admin/network/{id}/listings        network-admin (the owner)
    GET   /network-admin/network/{id}/listings/mine   tenant-admin, lead
    POST  /network-admin/network/{id}/listings
                                tenant-admin, lead: {service_id}
    POST  /network-admin/network/{id}/listings/{listing}/admit | reinstate    network-admin
    POST  /network-admin/network/{id}/listings/{listing}/decline | suspend
                                network-admin: {reason}
    POST  /network-admin/network/{id}/listings/{listing}/withdraw    tenant-admin, lead

Every POST is a state change the use case makes repeatable (the same command run again finishes
what stopped and changes nothing twice), so there is no `Idempotency-Key`: a client retries the
call. A failure names a part and never a value. No body holds a tenant id, an account reference, a
person or an agreement's content: the organisations are named, and the handles are the registry's
own ids.

The services are on `app.state.network_admin` (set by the process that serves the app, as the cache
and the network read services are); with none, the routes fail closed with a 500.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, Path, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from diucs.adapters.inbound.fhir_rest.auth import require_role
from diucs.application.actor import Actor
from diucs.application.use_cases.grants import (
    ApproveGrant,
    ApproveGrantCommand,
    DeclineGrant,
    DeclineGrantCommand,
    EndGrant,
    EndGrantCommand,
    GrantView,
    ProposeGrant,
    ProposeGrantCommand,
    QueryGrants,
    ReviseGrant,
    ReviseGrantCommand,
)
from diucs.application.use_cases.listing_admission import (
    DecideListing,
    DecideListingCommand,
    ListingDecision,
    ListingView,
    QueryListings,
    RequestListing,
    RequestListingCommand,
)
from diucs.application.use_cases.membership import (
    AcceptMembership,
    AcceptMembershipCommand,
    InviteMember,
    InviteMemberCommand,
    LeaveNetwork,
    LeaveNetworkCommand,
    RemoveMember,
    RemoveMemberCommand,
)
from diucs.application.use_cases.network_admin import (
    AdminMemberView,
    AdminNetworkView,
    MemberProjectionStatus,
    QueryNetworkAdmin,
    RecordAgreement,
    RecordAgreementCommand,
)
from diucs.domain.codes import Role
from diucs.domain.model.network import GrantScope, ListingReason

# The domain's patterns (kept equal by a test): a network id, and a registry record id.
NETWORK_ID_PATTERN: Final = r"^net-[a-z0-9][a-z0-9-]{1,26}$"
RECORD_ID_PATTERN: Final = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"
NO_STORE: Final = {"Cache-Control": "no-store"}

router = APIRouter(prefix="/network-admin")

TenantOrNetworkAdmin = Annotated[
    Actor, Depends(require_role(Role.TENANT_ADMIN, Role.NETWORK_ADMIN))
]
OwnerAdmin = Annotated[Actor, Depends(require_role(Role.NETWORK_ADMIN))]
TenantAdmin = Annotated[Actor, Depends(require_role(Role.TENANT_ADMIN))]
TenantAdminOrLead = Annotated[Actor, Depends(require_role(Role.TENANT_ADMIN, Role.LEAD))]
NetworkId = Annotated[str, Path(pattern=NETWORK_ID_PATTERN)]
RecordId = Annotated[str, Path(pattern=RECORD_ID_PATTERN)]


@dataclass(frozen=True, slots=True)
class NetworkAdminServices:
    query: QueryNetworkAdmin
    invite: InviteMember
    accept: AcceptMembership
    leave: LeaveNetwork
    remove: RemoveMember
    agreement: RecordAgreement
    grants: QueryGrants
    propose: ProposeGrant
    approve: ApproveGrant
    decline: DeclineGrant
    end: EndGrant
    revise: ReviseGrant
    listings: QueryListings
    request_listing: RequestListing
    decide_listing: DecideListing


def services(request: Request) -> NetworkAdminServices:
    # Fail closed: a missing wiring is a configuration error (a 500), never an empty answer.
    found: NetworkAdminServices | None = getattr(request.app.state, "network_admin", None)
    if found is None:
        raise RuntimeError("no network administration services are configured")
    return found


# ---------------------------------------------------------------- request bodies


class _Body(BaseModel):
    """An unknown field (a tenant, a network claim, an account) is a bad request."""

    model_config = ConfigDict(extra="forbid", strict=True)


class InviteBody(_Body):
    tenant_id: str


class AcceptBody(_Body):
    agreement_version: int


class AgreementBody(_Body):
    reference: str
    version: int


class ProposeBody(_Body):
    network_id: str
    scope: str
    effective_from: datetime | None = None
    effective_to: datetime | None = None


class ReviseBody(_Body):
    effective_from: datetime | None = None
    effective_to: datetime | None = None


class ListingBody(_Body):
    service_id: str


class ReasonBody(_Body):
    reason: str | None = None


# ---------------------------------------------------------------- response shapes


def _time(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat().replace("+00:00", "Z")


def _network(view: AdminNetworkView) -> dict[str, Any]:
    return {
        "id": view.network_id,
        "name": view.name,
        "status": view.status.value,
        "is_owner": view.is_owner,
        "membership_id": view.membership_id,
        "membership_status": view.membership_status.value,
        "agreement_reference": view.agreement_reference,
        "agreement_version": view.agreement_version,
        "accepted_agreement_version": view.accepted_agreement_version,
        "agreement_behind": view.agreement_behind,
        "system_name": view.system_name,
        "pathway_name": view.pathway_name,
        "time_zone": view.time_zone,
    }


def _member(view: AdminMemberView) -> dict[str, Any]:
    return {
        "membership_id": view.membership_id,
        "organisation_name": view.organisation_name,
        "role": view.role.value,
        "status": view.status.value,
        "invited_at": _time(view.invited_at),
        "joined_at": _time(view.joined_at),
        "left_at": _time(view.left_at),
        "accepted_agreement_version": view.accepted_agreement_version,
        "agreement_behind": view.agreement_behind,
    }


def _projection(view: MemberProjectionStatus) -> dict[str, Any]:
    return {
        "membership_id": view.membership_id,
        "organisation_name": view.organisation_name,
        "kinds": [
            {
                "kind": kind.kind.value,
                "status": kind.status.value,
                "ended_at": _time(kind.ended_at),
                "end_reason": None if kind.end_reason is None else kind.end_reason.value,
            }
            for kind in view.kinds
        ],
    }


def _grant(view: GrantView) -> dict[str, Any]:
    return {
        "id": view.grant_id,
        "network_id": view.network_id,
        "network_name": view.network_name,
        "organisation_name": view.organisation_name,
        "scope": view.scope.value,
        "status": view.status.value,
        "version": view.version,
        "effective_from": _time(view.effective_from),
        "effective_to": _time(view.effective_to),
        "agreement_version": view.agreement_version,
        "allowlist_version": view.allowlist_version,
        "grantor_approved_at": _time(view.grantor_approved_at),
        "owner_approved_at": _time(view.owner_approved_at),
        "ended_at": _time(view.ended_at),
        "end_reason": None if view.end_reason is None else view.end_reason.value,
        "supersedes_id": view.supersedes_id,
        "effective": view.effective,
    }


def _listing(view: ListingView) -> dict[str, Any]:
    return {
        "id": view.listing_id,
        "organisation_name": view.organisation_name,
        "service_id": view.service_id,
        "status": view.status.value,
        "reason": None if view.reason is None else view.reason.value,
        "requested_at": _time(view.requested_at),
        "decided_at": _time(view.decided_at),
    }


def _ok(body: dict[str, Any], status: int = 200) -> JSONResponse:
    return JSONResponse(body, status_code=status, headers=NO_STORE)


def _enum[E: GrantScope | ListingReason](cls: type[E], value: str | None, field: str) -> E | None:
    from diucs.domain.errors import ValidationFailed

    if value is None:
        return None
    try:
        return cls(value)
    except ValueError:
        raise ValidationFailed(field, "is not a valid value for this field") from None


# ---------------------------------------------------------------- the networks and the members


@router.get("/networks")
async def networks(request: Request, actor: TenantOrNetworkAdmin) -> JSONResponse:
    views = await services(request).query.networks(actor)
    return _ok({"networks": [_network(v) for v in views]})


@router.get("/network/{network_id}/members")
async def members(network_id: NetworkId, request: Request, actor: OwnerAdmin) -> JSONResponse:
    views = await services(request).query.members(actor, network_id)
    return _ok({"members": [_member(v) for v in views]})


@router.post("/network/{network_id}/members")
async def invite(
    network_id: NetworkId, body: InviteBody, request: Request, actor: OwnerAdmin
) -> JSONResponse:
    result = await services(request).invite.execute(
        InviteMemberCommand(actor, network_id, body.tenant_id)
    )
    return _ok({"membership_id": result.membership_id, "status": "invited"}, 201)


@router.post("/network/{network_id}/members/{membership_id}/remove")
async def remove(
    network_id: NetworkId, membership_id: RecordId, request: Request, actor: OwnerAdmin
) -> JSONResponse:
    result = await services(request).remove.execute(
        RemoveMemberCommand(actor, network_id, membership_id)
    )
    return _ok(
        {
            "status": "removed",
            "grants_lapsed": result.grants_lapsed,
            "listings_withdrawn": result.listings_withdrawn,
        }
    )


@router.post("/network/{network_id}/leave")
async def leave(network_id: NetworkId, request: Request, actor: TenantAdmin) -> JSONResponse:
    result = await services(request).leave.execute(LeaveNetworkCommand(actor, network_id))
    return _ok(
        {
            "status": "left",
            "grants_lapsed": result.grants_lapsed,
            "listings_withdrawn": result.listings_withdrawn,
        }
    )


@router.post("/memberships/{membership_id}/accept")
async def accept(
    membership_id: RecordId, body: AcceptBody, request: Request, actor: TenantAdmin
) -> JSONResponse:
    await services(request).accept.execute(
        AcceptMembershipCommand(actor, membership_id, body.agreement_version)
    )
    return _ok({"status": "active"})


@router.post("/network/{network_id}/agreement")
async def agreement(
    network_id: NetworkId, body: AgreementBody, request: Request, actor: OwnerAdmin
) -> JSONResponse:
    await services(request).agreement.execute(
        RecordAgreementCommand(actor, network_id, body.reference, body.version)
    )
    return _ok({"agreement_version": body.version})


@router.get("/network/{network_id}/projection")
async def projection(network_id: NetworkId, request: Request, actor: OwnerAdmin) -> JSONResponse:
    views = await services(request).query.projection_status(actor, network_id)
    return _ok({"members": [_projection(v) for v in views]})


# ---------------------------------------------------------------- grants


@router.get("/grants")
async def own_grants(request: Request, actor: TenantAdmin) -> JSONResponse:
    views = await services(request).grants.for_tenant(actor)
    return _ok({"grants": [_grant(v) for v in views]})


@router.get("/network/{network_id}/grants")
async def network_grants(
    network_id: NetworkId, request: Request, actor: OwnerAdmin
) -> JSONResponse:
    views = await services(request).grants.for_network(actor, network_id)
    return _ok({"grants": [_grant(v) for v in views]})


@router.post("/grants")
async def propose(body: ProposeBody, request: Request, actor: TenantAdmin) -> JSONResponse:
    scope = _enum(GrantScope, body.scope, "scope")
    assert scope is not None
    grant_id = await services(request).propose.execute(
        ProposeGrantCommand(actor, body.network_id, scope, body.effective_from, body.effective_to)
    )
    return _ok({"id": grant_id, "status": "proposed"}, 201)


@router.post("/grants/{grant_id}/approve")
async def approve(
    grant_id: RecordId, request: Request, actor: TenantOrNetworkAdmin
) -> JSONResponse:
    result = await services(request).approve.execute(ApproveGrantCommand(actor, grant_id))
    return _ok({"effective": result.effective})


@router.post("/grants/{grant_id}/decline")
async def decline(
    grant_id: RecordId, request: Request, actor: TenantOrNetworkAdmin
) -> JSONResponse:
    await services(request).decline.execute(DeclineGrantCommand(actor, grant_id))
    return _ok({"status": "declined"})


@router.post("/grants/{grant_id}/end")
async def end(grant_id: RecordId, request: Request, actor: TenantAdmin) -> JSONResponse:
    await services(request).end.execute(EndGrantCommand(actor, grant_id))
    return _ok({"status": "ended"})


@router.post("/grants/{grant_id}/revise")
async def revise(
    grant_id: RecordId, body: ReviseBody, request: Request, actor: TenantAdmin
) -> JSONResponse:
    revision_id = await services(request).revise.execute(
        ReviseGrantCommand(actor, grant_id, body.effective_from, body.effective_to)
    )
    return _ok({"id": revision_id, "status": "proposed"}, 201)


# ---------------------------------------------------------------- listings


@router.get("/network/{network_id}/listings")
async def listings(network_id: NetworkId, request: Request, actor: OwnerAdmin) -> JSONResponse:
    views = await services(request).listings.for_network(actor, network_id)
    return _ok({"listings": [_listing(v) for v in views]})


@router.get("/network/{network_id}/listings/mine")
async def own_listings(
    network_id: NetworkId, request: Request, actor: TenantAdminOrLead
) -> JSONResponse:
    views = await services(request).listings.of_member(actor, network_id)
    return _ok({"listings": [_listing(v) for v in views]})


@router.post("/network/{network_id}/listings")
async def request_listing(
    network_id: NetworkId, body: ListingBody, request: Request, actor: TenantAdminOrLead
) -> JSONResponse:
    listing_id = await services(request).request_listing.execute(
        RequestListingCommand(actor, network_id, body.service_id)
    )
    return _ok({"id": listing_id, "status": "pending"}, 201)


async def _decide(
    request: Request,
    actor: Actor,
    network_id: str,
    listing_id: str,
    decision: ListingDecision,
    body: ReasonBody | None,
) -> JSONResponse:
    reason = _enum(ListingReason, None if body is None else body.reason, "reason")
    await services(request).decide_listing.execute(
        DecideListingCommand(actor, network_id, listing_id, decision, reason)
    )
    return _ok({"status": "done"})


@router.post("/network/{network_id}/listings/{listing_id}/admit")
async def admit(
    network_id: NetworkId, listing_id: RecordId, request: Request, actor: OwnerAdmin
) -> JSONResponse:
    return await _decide(request, actor, network_id, listing_id, ListingDecision.ADMIT, None)


@router.post("/network/{network_id}/listings/{listing_id}/reinstate")
async def reinstate(
    network_id: NetworkId, listing_id: RecordId, request: Request, actor: OwnerAdmin
) -> JSONResponse:
    return await _decide(request, actor, network_id, listing_id, ListingDecision.REINSTATE, None)


@router.post("/network/{network_id}/listings/{listing_id}/decline")
async def decline_listing(
    network_id: NetworkId,
    listing_id: RecordId,
    body: ReasonBody,
    request: Request,
    actor: OwnerAdmin,
) -> JSONResponse:
    return await _decide(request, actor, network_id, listing_id, ListingDecision.DECLINE, body)


@router.post("/network/{network_id}/listings/{listing_id}/suspend")
async def suspend_listing(
    network_id: NetworkId,
    listing_id: RecordId,
    body: ReasonBody,
    request: Request,
    actor: OwnerAdmin,
) -> JSONResponse:
    return await _decide(request, actor, network_id, listing_id, ListingDecision.SUSPEND, body)


@router.post("/network/{network_id}/listings/{listing_id}/withdraw")
async def withdraw_listing(
    network_id: NetworkId, listing_id: RecordId, request: Request, actor: TenantAdminOrLead
) -> JSONResponse:
    return await _decide(request, actor, network_id, listing_id, ListingDecision.WITHDRAW, None)
