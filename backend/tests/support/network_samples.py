"""Sample network records for the network tests (TEN-051 onwards).

Every value is invented: `net-pilot`, `tenant-a` (the owner), `tenant-b` and `tenant-c` (members),
`UCR West`, an agreement reference `DSA-2026-1`. No real organisation, person or place. The records
are built through the domain's own functions, so a sample is always a record the domain accepts.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from diucs.domain.model.network import (
    Agreement,
    Grant,
    GrantApprover,
    GrantPurpose,
    GrantScope,
    Listing,
    MembershipEndReason,
    MembershipStatus,
    Network,
    NetworkMembership,
    NetworkStatus,
    accept_membership,
    activate_network,
    invite_member,
    owner_membership,
)
from diucs.domain.model.network_settings import NetworkSettings
from diucs.domain.rules.grant import approve_grant, propose_grant
from diucs.domain.rules.listing import admit_listing, request_listing

T0 = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
NOW = T0 + timedelta(days=30)
NETWORK_ID = "net-pilot"
OTHER_NETWORK_ID = "net-other"
OWNER = "tenant-a"
MEMBER_B = "tenant-b"
MEMBER_C = "tenant-c"
OUTSIDER = "tenant-z"
AGREEMENT = Agreement("DSA-2026-1", 1)
ACCOUNT_OWNER = "acct-owner-0001"
ACCOUNT_B = "acct-member-b-01"
ACCOUNT_C = "acct-member-c-01"
SETTINGS = NetworkSettings(
    system_name="Sample capacity board",
    pathway_name="Sample urgent pathway",
    time_zone="Europe/London",
)


def make_network(
    status: NetworkStatus = NetworkStatus.ACTIVE, *, id: str = NETWORK_ID, owner: str = OWNER
) -> Network:
    draft = Network(
        id=id,
        name="Sample network",
        owner_tenant_id=owner,
        status=NetworkStatus.DRAFT,
        agreement=None,
        created_at=T0,
        closed_at=None,
    )
    if status is NetworkStatus.DRAFT:
        return draft
    active = activate_network(draft, AGREEMENT, T0)
    if status is NetworkStatus.ACTIVE:
        return active
    if status is NetworkStatus.SUSPENDED:
        return replace(active, status=NetworkStatus.SUSPENDED)
    return replace(active, status=NetworkStatus.CLOSED, closed_at=T0 + timedelta(days=1))


def make_owner_membership(network: Network | None = None) -> NetworkMembership:
    return owner_membership(network or make_network(), "mem-owner", T0)


def make_member(
    tenant: str = MEMBER_B,
    *,
    status: MembershipStatus = MembershipStatus.ACTIVE,
    network: Network | None = None,
    id: str | None = None,
) -> NetworkMembership:
    net = network or make_network()
    invited = invite_member(net, [], id=id or f"mem-{tenant}", tenant_id=tenant, now=T0)
    if status is MembershipStatus.INVITED:
        return invited
    active = accept_membership(
        net,
        invited,
        agreement=AGREEMENT,
        account_ref="acct-accept-001",
        now=T0 + timedelta(hours=1),
    )
    if status is MembershipStatus.ACTIVE:
        return active
    if status is MembershipStatus.LEFT:
        return replace(
            active, status=MembershipStatus.LEFT, left_at=NOW, end_reason=MembershipEndReason.LEFT
        )
    return replace(
        active, status=MembershipStatus.REMOVED, left_at=NOW, end_reason=MembershipEndReason.REMOVED
    )


def make_grant(
    *,
    id: str = "grant-b-capacity",
    tenant: str = MEMBER_B,
    scope: GrantScope = GrantScope.CAPACITY,
    approved: bool = True,
    effective_from: datetime | None = None,
    effective_to: datetime | None = None,
    network_id: str = NETWORK_ID,
) -> Grant:
    grant = propose_grant(
        id=id,
        network_id=network_id,
        grantor_tenant_id=tenant,
        scope=scope,
        purpose=GrantPurpose.NETWORK_CAPACITY_VIEW,
        effective_from=effective_from or T0 + timedelta(hours=2),
        effective_to=effective_to,
        agreement=AGREEMENT,
        allowlist_version=1,
        proposed_by_account_ref=ACCOUNT_B,
        proposed_at=T0 + timedelta(hours=2),
    )
    if not approved:
        return grant
    grant = approve_grant(
        grant,
        approver=GrantApprover.GRANTOR,
        approver_tenant_id=tenant,
        network_owner_tenant_id=OWNER,
        account_ref=ACCOUNT_B,
        now=T0 + timedelta(hours=3),
    )
    return approve_grant(
        grant,
        approver=GrantApprover.OWNER,
        approver_tenant_id=OWNER,
        network_owner_tenant_id=OWNER,
        account_ref=ACCOUNT_OWNER,
        now=T0 + timedelta(hours=4),
    )


def make_listing(
    *, id: str = "lst-b-1", tenant: str = MEMBER_B, service: str = "svc-1", admitted: bool = True
) -> Listing:
    listing = request_listing(
        [],
        make_member(tenant),
        id=id,
        network_id=NETWORK_ID,
        source_service_id=service,
        now=T0 + timedelta(hours=5),
    )
    if not admitted:
        return listing
    return admit_listing(
        listing,
        by_tenant_id=OWNER,
        owner_tenant_id=OWNER,
        account_ref=ACCOUNT_OWNER,
        now=T0 + timedelta(hours=6),
    )
