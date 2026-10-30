"""The network registry on Neo4j (TEN-051, DEC-541, DEC-132, DEC-134 item 9).

The registry is the platform's record of its networks: `Network`, `NetworkMembership`, `Grant` and
`Listing` nodes, which carry no `tenantId`. Their statements run outside any scope (the projector's
gate runs in the member's tenant scope's worker before the network scope is bound, and the network
read use case checks the membership before it binds the network), so they are global statements on
the allowlist, pinned by digest, and run only through `run_global_query` (DEC-163). A read names
registry labels and nothing else. A write is a `CREATE` or a `SET` on a registry label, with no
delete, no procedure, no map assignment and no label assignment (`GLOBAL_WRITE_IDS`); each is one of

- a guarded create: a lock on the `Network` node first (a self-set), then a count of the live rows
  that would clash, and only when there is none the `CREATE` (a membership, a listing); or a plain
  `CREATE` whose unique key refuses a second row (a network, a grant);
- a compare-and-set: it matches the row by its key and the status the caller expects, so of two
  racing writers exactly one finds the row as expected, and the other writes nothing.

A statement returns the id it wrote, so no row means nothing was written, and the adapter turns
that, or a unique-key refusal, into `Conflict`. No statement takes a tenant: the `memberTenantId`,
`grantorTenantId`, `ownerTenantId` and `sourceTenantId` properties are data of the registry rows,
and the names were chosen so that no registry node looks like a node stamped with a scope.

A record is a node with typed properties (DEC-001): codes as text, times as datetimes, versions as
integers, an agreement as its reference and version (never its content), an approval as three
properties. A node the domain refuses is `NetworkRecordInvalid` with one fixed message that names no
id (a configuration fault, fail closed). Nothing is cached and nothing is logged here.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import StrEnum
from typing import Any, Final

from neo4j import AsyncManagedTransaction
from neo4j.exceptions import ConstraintError
from neo4j.time import DateTime

from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.outbound.graph_store.driver import run_global_query
from diucs.adapters.outbound.graph_store.queries import REGISTRY, NamedQuery
from diucs.application.ports.outbound.network import (
    ActiveGrant,
    NetworkRecordInvalid,
    RegisteredNetwork,
)
from diucs.domain.errors import Conflict, ValidationFailed
from diucs.domain.model.network import (
    Agreement,
    Approval,
    Grant,
    GrantPurpose,
    GrantScope,
    GrantStatus,
    Listing,
    ListingReason,
    ListingStatus,
    MembershipEndReason,
    MembershipRole,
    MembershipStatus,
    Network,
    NetworkMembership,
    NetworkStatus,
    check_network_id,
    check_tenant_field,
)
from diucs.domain.model.network_settings import NetworkSettings
from diucs.domain.rules.grant import may_project

RECORD_MESSAGE: Final = "a network record in the registry is not valid"
CONFLICT_MESSAGE: Final = "the registry row is not as expected, so nothing was written"

# The statements, written out in full (no Cypher is built from pieces, DEC-142 item 1). Each is on
# GLOBAL_QUERY_IDS with its reason and pinned in GLOBAL_STATEMENTS; test_global_allowlist.py and
# test_network_registry_statements.py pin every one.

_READS: Final[dict[str, str]] = {
    "Q-NETWORK-GET": "MATCH (n:Network {id: $id}) RETURN properties(n) AS network",
    "Q-NETWORK-MEMBERSHIPS": (
        "MATCH (m:NetworkMembership {networkId: $networkId}) "
        "RETURN properties(m) AS membership ORDER BY m.invitedAt, m.id"
    ),
    "Q-NETWORK-MEMBERSHIPS-OF": (
        "MATCH (m:NetworkMembership {memberTenantId: $memberTenantId}) "
        "RETURN properties(m) AS membership ORDER BY m.networkId, m.invitedAt, m.id"
    ),
    "Q-NETWORK-MEMBERSHIP-ACTIVE": (
        "MATCH (m:NetworkMembership {networkId: $networkId, memberTenantId: $memberTenantId, "
        "status: 'active'}) RETURN properties(m) AS membership"
    ),
    "Q-NETWORK-GRANT-GET": "MATCH (g:Grant {id: $id}) RETURN properties(g) AS grant",
    "Q-NETWORK-GRANTS": (
        "MATCH (g:Grant {networkId: $networkId}) RETURN properties(g) AS grant "
        "ORDER BY g.grantorTenantId, g.scope, g.version, g.id"
    ),
    "Q-NETWORK-GRANTS-OF": (
        "MATCH (g:Grant {grantorTenantId: $grantorTenantId}) RETURN properties(g) AS grant "
        "ORDER BY g.networkId, g.scope, g.version, g.id"
    ),
    "Q-NETWORK-GRANT-ACTIVE-FOR": (
        "MATCH (g:Grant {grantorTenantId: $grantorTenantId, scope: $scope, status: 'approved'}) "
        "MATCH (n:Network {id: g.networkId, status: 'active'}) "
        "MATCH (m:NetworkMembership {networkId: g.networkId, memberTenantId: g.grantorTenantId, "
        "status: 'active'}) "
        "RETURN properties(g) AS grant, properties(n) AS network, properties(m) AS membership "
        "ORDER BY g.networkId, g.version DESC, g.id"
    ),
    "Q-NETWORK-LISTING-GET": "MATCH (l:Listing {id: $id}) RETURN properties(l) AS listing",
    "Q-NETWORK-LISTINGS": (
        "MATCH (l:Listing {networkId: $networkId}) RETURN properties(l) AS listing "
        "ORDER BY l.sourceTenantId, l.serviceId, l.requestedAt, l.id"
    ),
    "Q-NETWORK-LISTINGS-OF": (
        "MATCH (l:Listing {networkId: $networkId, sourceTenantId: $sourceTenantId}) "
        "RETURN properties(l) AS listing ORDER BY l.serviceId, l.requestedAt, l.id"
    ),
}

_WRITES: Final[dict[str, str]] = {
    "Q-NETWORK-CREATE": (
        "CREATE (n:Network {id: $id, name: $name, ownerTenantId: $ownerTenantId, "
        "status: $status, agreementReference: $agreementReference, "
        "agreementVersion: $agreementVersion, createdAt: $createdAt, closedAt: $closedAt, "
        "systemName: $systemName, pathwayName: $pathwayName, timeZone: $timeZone}) "
        "RETURN n.id AS id"
    ),
    "Q-NETWORK-SAVE": (
        "MATCH (n:Network {id: $id, ownerTenantId: $ownerTenantId, status: $expectedStatus}) "
        "SET n.name = $name, n.status = $status, n.agreementReference = $agreementReference, "
        "n.agreementVersion = $agreementVersion, n.closedAt = $closedAt, "
        "n.systemName = $systemName, n.pathwayName = $pathwayName, n.timeZone = $timeZone "
        "RETURN n.id AS id"
    ),
    "Q-NETWORK-MEMBER-CREATE": (
        "MATCH (n:Network {id: $networkId}) SET n.status = n.status "
        "WITH n OPTIONAL MATCH (l:NetworkMembership {networkId: $networkId, "
        "memberTenantId: $memberTenantId}) WHERE l.status IN ['invited', 'active'] "
        "WITH n, count(l) AS live WHERE live = 0 "
        "CREATE (m:NetworkMembership {id: $id, networkId: $networkId, "
        "memberTenantId: $memberTenantId, role: $role, status: $status, invitedAt: $invitedAt, "
        "joinedAt: $joinedAt, leftAt: $leftAt, endReason: $endReason, "
        "acceptedAgreementReference: $acceptedAgreementReference, "
        "acceptedAgreementVersion: $acceptedAgreementVersion}) "
        "RETURN m.id AS id"
    ),
    "Q-NETWORK-MEMBER-SAVE": (
        "MATCH (m:NetworkMembership {id: $id, networkId: $networkId, "
        "memberTenantId: $memberTenantId, status: $expectedStatus}) "
        "SET m.status = $status, m.joinedAt = $joinedAt, m.leftAt = $leftAt, "
        "m.endReason = $endReason, m.acceptedAgreementReference = $acceptedAgreementReference, "
        "m.acceptedAgreementVersion = $acceptedAgreementVersion "
        "RETURN m.id AS id"
    ),
    "Q-NETWORK-GRANT-CREATE": (
        "CREATE (g:Grant {id: $id, networkId: $networkId, grantorTenantId: $grantorTenantId, "
        "scope: $scope, purpose: $purpose, version: $version, status: $status, "
        "effectiveFrom: $effectiveFrom, effectiveTo: $effectiveTo, "
        "agreementReference: $agreementReference, agreementVersion: $agreementVersion, "
        "allowlistVersion: $allowlistVersion, proposedByAccountRef: $proposedByAccountRef, "
        "proposedAt: $proposedAt, grantorApprovalAccountRef: $grantorApprovalAccountRef, "
        "grantorApprovalTenantId: $grantorApprovalTenantId, "
        "grantorApprovalAt: $grantorApprovalAt, "
        "ownerApprovalAccountRef: $ownerApprovalAccountRef, "
        "ownerApprovalTenantId: $ownerApprovalTenantId, ownerApprovalAt: $ownerApprovalAt, "
        "endedAt: $endedAt, endedByAccountRef: $endedByAccountRef, "
        "supersedesId: $supersedesId}) "
        "RETURN g.id AS id"
    ),
    "Q-NETWORK-GRANT-SAVE": (
        "MATCH (g:Grant {id: $id, networkId: $networkId, grantorTenantId: $grantorTenantId, "
        "status: $expectedStatus}) "
        "SET g.status = $status, g.effectiveTo = $effectiveTo, "
        "g.grantorApprovalAccountRef = $grantorApprovalAccountRef, "
        "g.grantorApprovalTenantId = $grantorApprovalTenantId, "
        "g.grantorApprovalAt = $grantorApprovalAt, "
        "g.ownerApprovalAccountRef = $ownerApprovalAccountRef, "
        "g.ownerApprovalTenantId = $ownerApprovalTenantId, "
        "g.ownerApprovalAt = $ownerApprovalAt, g.endedAt = $endedAt, "
        "g.endedByAccountRef = $endedByAccountRef "
        "RETURN g.id AS id"
    ),
    "Q-NETWORK-LISTING-CREATE": (
        "MATCH (n:Network {id: $networkId}) SET n.status = n.status "
        "WITH n OPTIONAL MATCH (l:Listing {networkId: $networkId, sourceTenantId: $sourceTenantId, "
        "serviceId: $serviceId}) "
        "WHERE l.status IN ['pending', 'admitted', 'suspended'] "
        "WITH n, count(l) AS live WHERE live = 0 "
        "CREATE (x:Listing {id: $id, networkId: $networkId, sourceTenantId: $sourceTenantId, "
        "serviceId: $serviceId, status: $status, requestedAt: $requestedAt, "
        "decidedAt: $decidedAt, decidedByAccountRef: $decidedByAccountRef, reason: $reason}) "
        "RETURN x.id AS id"
    ),
    "Q-NETWORK-LISTING-SAVE": (
        "MATCH (l:Listing {id: $id, networkId: $networkId, sourceTenantId: $sourceTenantId, "
        "serviceId: $serviceId, status: $expectedStatus}) "
        "SET l.status = $status, l.decidedAt = $decidedAt, "
        "l.decidedByAccountRef = $decidedByAccountRef, l.reason = $reason "
        "RETURN l.id AS id"
    ),
}


def _query(query_id: str, cypher: str, mode: str) -> NamedQuery:
    query = NamedQuery(id=query_id, cypher=cypher, mode=mode, scope="global")  # type: ignore[arg-type]
    REGISTRY.register(query)
    return query


_STATEMENTS: Final[dict[str, NamedQuery]] = {
    **{query_id: _query(query_id, text, "read") for query_id, text in _READS.items()},
    **{query_id: _query(query_id, text, "write") for query_id, text in _WRITES.items()},
}


# ---------------------------------------------------------------- the records and their nodes


class _Invalid(Exception):
    """Internal: a property is missing or of the wrong type. Never leaves this module."""


def _optional_text(props: Mapping[str, Any], key: str) -> str | None:
    value = props.get(key)
    if value is None:
        return None
    if type(value) is not str:
        raise _Invalid
    return value


def _text(props: Mapping[str, Any], key: str) -> str:
    value = _optional_text(props, key)
    if value is None:
        raise _Invalid
    return value


def _code[E: StrEnum](props: Mapping[str, Any], key: str, kind: type[E]) -> E:
    return kind(_text(props, key))


def _optional_code[E: StrEnum](props: Mapping[str, Any], key: str, kind: type[E]) -> E | None:
    value = _optional_text(props, key)
    return None if value is None else kind(value)


def _optional_instant(props: Mapping[str, Any], key: str) -> datetime | None:
    value = props.get(key)
    if value is None:
        return None
    native = value.to_native() if isinstance(value, DateTime) else value
    if not isinstance(native, datetime):
        raise _Invalid  # a time held as text, or as anything but a datetime
    return native


def _instant(props: Mapping[str, Any], key: str) -> datetime:
    value = _optional_instant(props, key)
    if value is None:
        raise _Invalid
    return value


def _count(props: Mapping[str, Any], key: str) -> int:
    value = props.get(key)
    if type(value) is not int:
        raise _Invalid
    return value


def _agreement(props: Mapping[str, Any], reference: str, version: str) -> Agreement | None:
    ref = _optional_text(props, reference)
    number = props.get(version)
    if ref is None and number is None:
        return None
    if ref is None or type(number) is not int:
        raise _Invalid
    return Agreement(ref, number)


def _approval(props: Mapping[str, Any], prefix: str) -> Approval | None:
    account = _optional_text(props, f"{prefix}AccountRef")
    tenant = _optional_text(props, f"{prefix}TenantId")
    at = _optional_instant(props, f"{prefix}At")
    if account is None and tenant is None and at is None:
        return None
    if account is None or tenant is None or at is None:
        raise _Invalid
    return Approval(account_ref=account, tenant_id=tenant, at=at)


def network_properties(network: Network, settings: NetworkSettings) -> dict[str, Any]:
    """The properties of a network's node, settings included. An unset field is `None` (a `SET`
    removes the property and a `CREATE` leaves it out, so the node holds no null)."""
    agreement = network.agreement
    return {
        "id": network.id,
        "name": network.name,
        "ownerTenantId": network.owner_tenant_id,
        "status": network.status.value,
        "agreementReference": None if agreement is None else agreement.reference,
        "agreementVersion": None if agreement is None else agreement.version,
        "createdAt": network.created_at,
        "closedAt": network.closed_at,
        "systemName": settings.system_name,
        "pathwayName": settings.pathway_name,
        "timeZone": settings.time_zone,
    }


def network_from_properties(props: Mapping[str, Any]) -> RegisteredNetwork:
    """The network and settings a node holds, through the domain's own checks. A missing or
    mistyped property, a status that disagrees with its agreement or dates, an id that is not a
    network id: `NetworkRecordInvalid`, with a fixed message that holds no value."""
    try:
        network = Network(
            id=_text(props, "id"),
            name=_text(props, "name"),
            owner_tenant_id=_text(props, "ownerTenantId"),
            status=_code(props, "status", NetworkStatus),
            agreement=_agreement(props, "agreementReference", "agreementVersion"),
            created_at=_instant(props, "createdAt"),
            closed_at=_optional_instant(props, "closedAt"),
        )
        settings = NetworkSettings(
            system_name=_text(props, "systemName"),
            pathway_name=_text(props, "pathwayName"),
            time_zone=_text(props, "timeZone"),
        )
    except _Invalid, ValidationFailed, ValueError, TypeError:
        raise NetworkRecordInvalid(RECORD_MESSAGE) from None
    return RegisteredNetwork(network, settings)


def membership_properties(row: NetworkMembership) -> dict[str, Any]:
    accepted = row.accepted_agreement
    return {
        "id": row.id,
        "networkId": row.network_id,
        "memberTenantId": row.member_tenant_id,
        "role": row.role.value,
        "status": row.status.value,
        "invitedAt": row.invited_at,
        "joinedAt": row.joined_at,
        "leftAt": row.left_at,
        "endReason": None if row.end_reason is None else row.end_reason.value,
        "acceptedAgreementReference": None if accepted is None else accepted.reference,
        "acceptedAgreementVersion": None if accepted is None else accepted.version,
    }


def membership_from_properties(props: Mapping[str, Any]) -> NetworkMembership:
    try:
        return NetworkMembership(
            id=_text(props, "id"),
            network_id=_text(props, "networkId"),
            member_tenant_id=_text(props, "memberTenantId"),
            role=_code(props, "role", MembershipRole),
            status=_code(props, "status", MembershipStatus),
            invited_at=_instant(props, "invitedAt"),
            joined_at=_optional_instant(props, "joinedAt"),
            left_at=_optional_instant(props, "leftAt"),
            end_reason=_optional_code(props, "endReason", MembershipEndReason),
            accepted_agreement=_agreement(
                props, "acceptedAgreementReference", "acceptedAgreementVersion"
            ),
        )
    except _Invalid, ValidationFailed, ValueError, TypeError:
        raise NetworkRecordInvalid(RECORD_MESSAGE) from None


def grant_properties(grant: Grant) -> dict[str, Any]:
    grantor, owner = grant.grantor_approval, grant.owner_approval
    return {
        "id": grant.id,
        "networkId": grant.network_id,
        "grantorTenantId": grant.grantor_tenant_id,
        "scope": grant.scope.value,
        "purpose": grant.purpose.value,
        "version": grant.version,
        "status": grant.status.value,
        "effectiveFrom": grant.effective_from,
        "effectiveTo": grant.effective_to,
        "agreementReference": grant.agreement.reference,
        "agreementVersion": grant.agreement.version,
        "allowlistVersion": grant.allowlist_version,
        "proposedByAccountRef": grant.proposed_by_account_ref,
        "proposedAt": grant.proposed_at,
        "grantorApprovalAccountRef": None if grantor is None else grantor.account_ref,
        "grantorApprovalTenantId": None if grantor is None else grantor.tenant_id,
        "grantorApprovalAt": None if grantor is None else grantor.at,
        "ownerApprovalAccountRef": None if owner is None else owner.account_ref,
        "ownerApprovalTenantId": None if owner is None else owner.tenant_id,
        "ownerApprovalAt": None if owner is None else owner.at,
        "endedAt": grant.ended_at,
        "endedByAccountRef": grant.ended_by_account_ref,
        "supersedesId": grant.supersedes_id,
    }


def grant_from_properties(props: Mapping[str, Any]) -> Grant:
    try:
        agreement = _agreement(props, "agreementReference", "agreementVersion")
        if agreement is None:
            raise _Invalid
        return Grant(
            id=_text(props, "id"),
            network_id=_text(props, "networkId"),
            grantor_tenant_id=_text(props, "grantorTenantId"),
            scope=_code(props, "scope", GrantScope),
            purpose=_code(props, "purpose", GrantPurpose),
            version=_count(props, "version"),
            status=_code(props, "status", GrantStatus),
            effective_from=_instant(props, "effectiveFrom"),
            effective_to=_optional_instant(props, "effectiveTo"),
            agreement=agreement,
            allowlist_version=_count(props, "allowlistVersion"),
            proposed_by_account_ref=_text(props, "proposedByAccountRef"),
            proposed_at=_instant(props, "proposedAt"),
            grantor_approval=_approval(props, "grantorApproval"),
            owner_approval=_approval(props, "ownerApproval"),
            ended_at=_optional_instant(props, "endedAt"),
            ended_by_account_ref=_optional_text(props, "endedByAccountRef"),
            supersedes_id=_optional_text(props, "supersedesId"),
        )
    except _Invalid, ValidationFailed, ValueError, TypeError:
        raise NetworkRecordInvalid(RECORD_MESSAGE) from None


def listing_properties(listing: Listing) -> dict[str, Any]:
    return {
        "id": listing.id,
        "networkId": listing.network_id,
        "sourceTenantId": listing.source_tenant_id,
        "serviceId": listing.source_service_id,
        "status": listing.status.value,
        "requestedAt": listing.requested_at,
        "decidedAt": listing.decided_at,
        "decidedByAccountRef": listing.decided_by_account_ref,
        "reason": None if listing.reason is None else listing.reason.value,
    }


def listing_from_properties(props: Mapping[str, Any]) -> Listing:
    try:
        return Listing(
            id=_text(props, "id"),
            network_id=_text(props, "networkId"),
            source_tenant_id=_text(props, "sourceTenantId"),
            source_service_id=_text(props, "serviceId"),
            status=_code(props, "status", ListingStatus),
            requested_at=_instant(props, "requestedAt"),
            decided_at=_optional_instant(props, "decidedAt"),
            decided_by_account_ref=_optional_text(props, "decidedByAccountRef"),
            reason=_optional_code(props, "reason", ListingReason),
        )
    except _Invalid, ValidationFailed, ValueError, TypeError:
        raise NetworkRecordInvalid(RECORD_MESSAGE) from None


# ---------------------------------------------------------------- the adapter


def _valid_network(value: object) -> bool:
    try:
        check_network_id(value)
    except ValidationFailed:
        return False
    return True


def _valid_tenant(value: object) -> bool:
    try:
        check_tenant_field(value, "tenant_id")
    except ValidationFailed:
        return False
    return True


class Neo4jNetworkRegistry:
    """The `NetworkRegistry` port over the registry nodes, on the process's one connection."""

    def __init__(self, connection: Neo4jConnection) -> None:
        self._connection = connection

    async def _read(self, query_id: str, **params: Any) -> list[dict[str, Any]]:
        query = _STATEMENTS[query_id]

        async def work(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
            return await run_global_query(tx, query, **params)

        return await self._connection.run_read(work)

    async def _write(self, query_id: str, params: dict[str, Any]) -> None:
        """Run a write; no row back, or a unique key that is taken, is a Conflict."""
        query = _STATEMENTS[query_id]

        async def work(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
            return await run_global_query(tx, query, **params)

        try:
            rows = await self._connection.run_write(work)
        except ConstraintError:
            raise Conflict(CONFLICT_MESSAGE) from None
        if not rows:
            raise Conflict(CONFLICT_MESSAGE)

    # ---- reads

    async def get_network(self, network_id: str) -> RegisteredNetwork | None:
        if not _valid_network(network_id):
            return None
        rows = await self._read("Q-NETWORK-GET", id=network_id)
        if not rows:
            return None
        if len(rows) > 1:  # the id is unique, so this is a registry fault
            raise NetworkRecordInvalid(RECORD_MESSAGE)
        return network_from_properties(rows[0]["network"])

    async def memberships(self, network_id: str) -> Sequence[NetworkMembership]:
        if not _valid_network(network_id):
            return []
        rows = await self._read("Q-NETWORK-MEMBERSHIPS", networkId=network_id)
        return [membership_from_properties(row["membership"]) for row in rows]

    async def memberships_of(self, tenant_id: str) -> Sequence[NetworkMembership]:
        if not _valid_tenant(tenant_id):
            return []
        rows = await self._read("Q-NETWORK-MEMBERSHIPS-OF", memberTenantId=tenant_id)
        return [membership_from_properties(row["membership"]) for row in rows]

    async def active_membership(self, network_id: str, tenant_id: str) -> NetworkMembership | None:
        if not _valid_network(network_id) or not _valid_tenant(tenant_id):
            return None
        rows = await self._read(
            "Q-NETWORK-MEMBERSHIP-ACTIVE", networkId=network_id, memberTenantId=tenant_id
        )
        if not rows:
            return None
        if len(rows) > 1:  # one live row per tenant and network, so this is a registry fault
            raise NetworkRecordInvalid(RECORD_MESSAGE)
        return membership_from_properties(rows[0]["membership"])

    async def get_grant(self, grant_id: str) -> Grant | None:
        if type(grant_id) is not str or not grant_id:
            return None
        rows = await self._read("Q-NETWORK-GRANT-GET", id=grant_id)
        if not rows:
            return None
        if len(rows) > 1:
            raise NetworkRecordInvalid(RECORD_MESSAGE)
        return grant_from_properties(rows[0]["grant"])

    async def grants(self, network_id: str) -> Sequence[Grant]:
        if not _valid_network(network_id):
            return []
        rows = await self._read("Q-NETWORK-GRANTS", networkId=network_id)
        return [grant_from_properties(row["grant"]) for row in rows]

    async def grants_of(self, tenant_id: str) -> Sequence[Grant]:
        if not _valid_tenant(tenant_id):
            return []
        rows = await self._read("Q-NETWORK-GRANTS-OF", grantorTenantId=tenant_id)
        return [grant_from_properties(row["grant"]) for row in rows]

    async def active_grants_for(
        self, tenant_id: str, scope: GrantScope, now: datetime
    ) -> Sequence[ActiveGrant]:
        """The statement selects the approved grants of an active network with the grantor's active
        membership; the domain's `may_project` then decides, at `now`, from the dates (a grant that
        has not started, or has ended its window, is dropped here)."""
        if type(scope) is not GrantScope:
            raise ValidationFailed("scope", "is not a valid value for this field")
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValidationFailed("now", "must be a timezone-aware datetime")
        if not _valid_tenant(tenant_id):
            return []
        rows = await self._read(
            "Q-NETWORK-GRANT-ACTIVE-FOR", grantorTenantId=tenant_id, scope=scope.value
        )
        active: list[ActiveGrant] = []
        for row in rows:
            grant = grant_from_properties(row["grant"])
            membership = membership_from_properties(row["membership"])
            network = network_from_properties(row["network"])
            if (
                may_project(grant, membership, now)
                and network.network.status is NetworkStatus.ACTIVE
            ):
                active.append(ActiveGrant(network, grant, membership))
        return active

    async def get_listing(self, listing_id: str) -> Listing | None:
        if type(listing_id) is not str or not listing_id:
            return None
        rows = await self._read("Q-NETWORK-LISTING-GET", id=listing_id)
        if not rows:
            return None
        if len(rows) > 1:
            raise NetworkRecordInvalid(RECORD_MESSAGE)
        return listing_from_properties(rows[0]["listing"])

    async def listings(self, network_id: str) -> Sequence[Listing]:
        if not _valid_network(network_id):
            return []
        rows = await self._read("Q-NETWORK-LISTINGS", networkId=network_id)
        return [listing_from_properties(row["listing"]) for row in rows]

    async def listings_of(self, network_id: str, tenant_id: str) -> Sequence[Listing]:
        if not _valid_network(network_id) or not _valid_tenant(tenant_id):
            return []
        rows = await self._read(
            "Q-NETWORK-LISTINGS-OF", networkId=network_id, sourceTenantId=tenant_id
        )
        return [listing_from_properties(row["listing"]) for row in rows]

    # ---- writes

    async def create_network(self, network: Network, settings: NetworkSettings) -> None:
        await self._write("Q-NETWORK-CREATE", network_properties(network, settings))

    async def save_network(
        self, network: Network, settings: NetworkSettings, *, expected_status: NetworkStatus
    ) -> None:
        params = {**network_properties(network, settings), "expectedStatus": expected_status.value}
        await self._write("Q-NETWORK-SAVE", params)

    async def create_membership(self, membership: NetworkMembership) -> None:
        await self._write("Q-NETWORK-MEMBER-CREATE", membership_properties(membership))

    async def save_membership(
        self, membership: NetworkMembership, *, expected_status: MembershipStatus
    ) -> None:
        params = {**membership_properties(membership), "expectedStatus": expected_status.value}
        await self._write("Q-NETWORK-MEMBER-SAVE", params)

    async def create_grant(self, grant: Grant) -> None:
        await self._write("Q-NETWORK-GRANT-CREATE", grant_properties(grant))

    async def save_grant(self, grant: Grant, *, expected_status: GrantStatus) -> None:
        params = {**grant_properties(grant), "expectedStatus": expected_status.value}
        await self._write("Q-NETWORK-GRANT-SAVE", params)

    async def create_listing(self, listing: Listing) -> None:
        await self._write("Q-NETWORK-LISTING-CREATE", listing_properties(listing))

    async def save_listing(self, listing: Listing, *, expected_status: ListingStatus) -> None:
        params = {**listing_properties(listing), "expectedStatus": expected_status.value}
        await self._write("Q-NETWORK-LISTING-SAVE", params)
