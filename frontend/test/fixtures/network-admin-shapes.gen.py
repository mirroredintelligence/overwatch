"""Writes frontend/test/fixtures/network-admin-shapes.ts: the JSON the back end answers on the network
and grant administration routes (`/network-admin/...`, TEN-079, and the sharing read, TEN-081), produced
by the route module's own converters, so a front-end test never holds a shape the back end does not send.
Sample values only. Run from backend/:

    uv run python ../frontend/test/fixtures/network-admin-shapes.gen.py > ../frontend/test/fixtures/network-admin-shapes.ts

Re-run it when a route's answer changes.
"""

import json
from datetime import UTC, datetime, timedelta

from diucs.adapters.inbound.fhir_rest.routes_network_admin import (
    _grant,
    _listing,
    _member,
    _network,
    _projection,
    _sharing,
)
from diucs.application.ports.outbound.projection import ProjectionEndReason, SourceStatus
from diucs.application.use_cases.grants import GrantView
from diucs.application.use_cases.listing_admission import ListingView
from diucs.application.use_cases.member_sharing import (
    MemberSharingNetwork,
    MemberSharingView,
    SharedKindView,
    allowlist_fields,
)
from diucs.application.use_cases.network_admin import (
    AdminMemberView,
    AdminNetworkView,
    KindStatus,
    MemberProjectionStatus,
)
from diucs.domain.model.network import (
    GrantEndReason,
    GrantScope,
    GrantStatus,
    ListingReason,
    ListingStatus,
    MembershipRole,
    MembershipStatus,
    NetworkStatus,
)

T0 = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
NOW = datetime(2026, 10, 30, 10, 0, tzinfo=UTC)


def network(*, owner: bool, status: MembershipStatus = MembershipStatus.ACTIVE, behind: bool = False) -> dict:
    return _network(
        AdminNetworkView(
            network_id="net-sample",
            name="Sample Network",
            status=NetworkStatus.ACTIVE,
            is_owner=owner,
            membership_id="mem-owner" if owner else "mem-a",
            membership_status=status,
            agreement_reference="DSA-2026-1" if not behind else "DSA-2026-2",
            agreement_version=2 if behind else 1,
            accepted_agreement_version=1,
            agreement_behind=behind,
            system_name="Sample capacity",
            pathway_name="Sample pathway",
            time_zone="Europe/London",
        )
    )


def member(mid: str, name: str, status: MembershipStatus, role: MembershipRole = MembershipRole.MEMBER, *, behind: bool = False, left: bool = False) -> dict:
    return _member(
        AdminMemberView(
            membership_id=mid,
            organisation_name=name,
            role=role,
            status=status,
            invited_at=T0,
            joined_at=None if status is MembershipStatus.INVITED else T0 + timedelta(days=1),
            left_at=NOW - timedelta(days=2) if left else None,
            accepted_agreement_version=None if status is MembershipStatus.INVITED else 1,
            agreement_behind=behind,
        )
    )


def grant(gid: str, org: str, scope: GrantScope, status: GrantStatus, *, effective: bool = False, grantor: bool = False, owner: bool = False, ended: GrantEndReason | None = None) -> dict:
    return _grant(
        GrantView(
            grant_id=gid,
            network_id="net-sample",
            network_name="Sample Network",
            organisation_name=org,
            scope=scope,
            status=status,
            version=1,
            effective_from=T0 + timedelta(days=3),
            effective_to=NOW + timedelta(days=300) if scope is GrantScope.CRITERIA else None,
            agreement_version=1,
            allowlist_version=1,
            grantor_approved_at=T0 + timedelta(days=3) if grantor else None,
            owner_approved_at=T0 + timedelta(days=4) if owner else None,
            ended_at=NOW - timedelta(days=1) if ended is not None else None,
            end_reason=ended,
            supersedes_id=None,
            effective=effective,
        )
    )


def listing(lid: str, org: str, service: str, status: ListingStatus, reason: ListingReason | None = None) -> dict:
    return _listing(
        ListingView(
            listing_id=lid,
            organisation_name=org,
            service_id=service,
            status=status,
            reason=reason,
            requested_at=T0 + timedelta(days=5),
            decided_at=None if status is ListingStatus.PENDING else T0 + timedelta(days=6),
        )
    )


OWNER_NETWORKS = {"networks": [network(owner=True)]}
MEMBER_NETWORKS = {"networks": [network(owner=False)]}

MEMBERS = {
    "members": [
        member("mem-owner", "Sample Lead Organisation", MembershipStatus.ACTIVE, MembershipRole.OWNER),
        member("mem-a", "Sample Area A", MembershipStatus.ACTIVE),
        member("mem-b", "Sample Area B", MembershipStatus.ACTIVE, behind=True),
        member("mem-c", "Sample Area C", MembershipStatus.INVITED),
        member("mem-d", "Sample Area D", MembershipStatus.LEFT, left=True),
        member("mem-e", "Sample Area E", MembershipStatus.REMOVED, left=True),
    ]
}

GRANTS = {
    "grants": [
        grant("grant-1", "Sample Area A", GrantScope.CAPACITY, GrantStatus.GRANTOR_APPROVED, grantor=True),
        grant("grant-2", "Sample Area A", GrantScope.DIRECTORY, GrantStatus.APPROVED, effective=True, grantor=True, owner=True),
        grant("grant-3", "Sample Area B", GrantScope.CAPACITY, GrantStatus.PROPOSED),
        grant("grant-4", "Sample Area B", GrantScope.CRITERIA, GrantStatus.ENDED, grantor=True, owner=True, ended=GrantEndReason.ENDED),
        grant("grant-5", "Sample Area D", GrantScope.CAPACITY, GrantStatus.LAPSED, grantor=True, owner=True, ended=GrantEndReason.LAPSED),
        grant("grant-6", "Sample Area A", GrantScope.CRITERIA, GrantStatus.DECLINED),
        grant("grant-7", "Sample Area A", GrantScope.CAPACITY, GrantStatus.OWNER_APPROVED, owner=True),
    ]
}

LISTINGS = {
    "listings": [
        listing("lst-1", "Sample Area A", "svc-ucr-west", ListingStatus.PENDING),
        listing("lst-2", "Sample Area A", "svc-sdec", ListingStatus.ADMITTED),
        listing("lst-3", "Sample Area B", "svc-beds", ListingStatus.SUSPENDED, ListingReason.DATA_QUALITY),
        listing("lst-4", "Sample Area B", "svc-virtual", ListingStatus.DECLINED, ListingReason.OUTSIDE_AREA),
        listing("lst-5", "Sample Area D", "svc-care", ListingStatus.WITHDRAWN),
    ]
}

PROJECTION = {
    "members": [
        _projection(
            MemberProjectionStatus(
                membership_id="mem-a",
                organisation_name="Sample Area A",
                kinds=(
                    KindStatus(GrantScope.CAPACITY, SourceStatus.ACTIVE, None, None),
                    KindStatus(GrantScope.DIRECTORY, SourceStatus.ACTIVE, None, None),
                ),
            )
        ),
        _projection(
            MemberProjectionStatus(
                membership_id="mem-d",
                organisation_name="Sample Area D",
                kinds=(KindStatus(GrantScope.CAPACITY, SourceStatus.ENDED, NOW - timedelta(days=2), ProjectionEndReason.LEFT),),
            )
        ),
    ]
}

SHARING = _sharing(
    MemberSharingView(
        allowlist_version=1,
        allowlist=allowlist_fields(),
        networks=(
            MemberSharingNetwork(
                network_id="net-sample",
                name="Sample Network",
                membership_id="mem-a",
                membership_status=MembershipStatus.ACTIVE,
                joined_at=T0 + timedelta(days=1),
                left_at=None,
                agreement_reference="DSA-2026-1",
                agreement_version=1,
                accepted_agreement_version=1,
                agreement_behind=False,
                kinds=(
                    SharedKindView(GrantScope.CAPACITY, SourceStatus.ACTIVE, None, None),
                    SharedKindView(GrantScope.DIRECTORY, SourceStatus.ENDED, NOW - timedelta(days=1), ProjectionEndReason.GRANT_ENDED),
                ),
            ),
        ),
    )
)

print("// GENERATED by network-admin-shapes.gen.py from the back end's own converters (TEN-079, TEN-081). Do not edit.")
print("// Sample values only: no patient data.")
for name, value in [
    ("OWNER_NETWORKS", OWNER_NETWORKS),
    ("MEMBER_NETWORKS", MEMBER_NETWORKS),
    ("MEMBERS", MEMBERS),
    ("GRANTS", GRANTS),
    ("LISTINGS", LISTINGS),
    ("PROJECTION", PROJECTION),
    ("SHARING", SHARING),
]:
    print(f"export const {name} = {json.dumps(value, indent=2)};")
