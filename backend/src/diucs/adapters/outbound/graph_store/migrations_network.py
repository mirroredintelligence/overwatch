"""Migrations of the network registry (TEN-051) and of the network scope's projections (TEN-053).

Migration 0110 (the first id of the block 0110 to 0129 given to build wave 5, bundle W5E) makes the
registry's keys unique and indexes the lookups the gate and the membership check make: a network, a
membership, a grant and a listing by id; a grant by its network, grantor, scope and version (a
change is a new version, never a second row of the same one); and the reads by member, by grantor
and scope, by network and by source. The registry nodes carry no `tenantId` (DEC-132, DEC-134
item 9), so no key here has one: they are global by design and reached only by global statements.

One schema statement each (lesson L8: a schema statement runs in its own transaction), idempotent
(`IF NOT EXISTS`), fixed text written out in full (DEC-142 item 1). Expand only: nothing is dropped
and no data is written, because no registry label existed before (a node with one of these labels
is created only by TEN-051's statements).

Migration 0111 (TEN-053) makes the keys of the network scope's nodes unique, each composite with the
scope and with the member the row came from, and indexes the live reads. A constraint ignores a node
that has no `tenantId`, so the invariant check counts those (TEN-031). Expand only again: no label
existed before, so nothing is dropped.
"""

from dataclasses import dataclass
from typing import Final

from diucs.adapters.outbound.graph_store.migration_types import Migration


@dataclass(frozen=True, slots=True)
class RegistryConstraint:
    """A key of the registry: its name, label and properties (the statement below is its text)."""

    name: str
    label: str
    properties: tuple[str, ...]


NETWORK_REGISTRY_CONSTRAINTS: Final[tuple[RegistryConstraint, ...]] = (
    RegistryConstraint("network_id", "Network", ("id",)),
    RegistryConstraint("network_membership_id", "NetworkMembership", ("id",)),
    RegistryConstraint("network_grant_id", "Grant", ("id",)),
    RegistryConstraint(
        "network_grant_version", "Grant", ("networkId", "grantorTenantId", "scope", "version")
    ),
    RegistryConstraint("network_listing_id", "Listing", ("id",)),
)

# The keys of the network scope (TEN-053). Every one is composite with the scope (`tenantId` is
# the network's id there) and with the member the row came from, so two members' services that
# share an id never meet and two networks never meet.
PROJECTION_CONSTRAINTS: Final[tuple[RegistryConstraint, ...]] = (
    RegistryConstraint(
        "projection_source", "ProjectionSource", ("tenantId", "sourceTenantId", "kind")
    ),
    RegistryConstraint(
        "projected_service", "ProjectedService", ("tenantId", "sourceTenantId", "sourceServiceId")
    ),
    RegistryConstraint(
        "projected_location", "ProjectedLocation", ("tenantId", "sourceTenantId", "sourceServiceId")
    ),
    RegistryConstraint(
        "projected_opening_hour",
        "ProjectedOpeningHour",
        ("tenantId", "sourceTenantId", "sourceServiceId", "position"),
    ),
    RegistryConstraint(
        "projected_capacity", "ProjectedCapacity", ("tenantId", "sourceTenantId", "sourceServiceId")
    ),
    RegistryConstraint(
        "projected_criteria", "ProjectedCriteria", ("tenantId", "sourceTenantId", "sourceServiceId")
    ),
    RegistryConstraint(
        "projection_cursor", "ProjectionCursor", ("tenantId", "sourceTenantId", "kind")
    ),
)

NETWORK_MIGRATIONS: Final[tuple[Migration, ...]] = (
    Migration(
        "0110_network_registry",
        statements=(
            "CREATE CONSTRAINT network_id IF NOT EXISTS FOR (n:Network) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT network_membership_id IF NOT EXISTS "
            "FOR (n:NetworkMembership) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT network_grant_id IF NOT EXISTS FOR (n:Grant) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT network_grant_version IF NOT EXISTS FOR (n:Grant) "
            "REQUIRE (n.networkId, n.grantorTenantId, n.scope, n.version) IS UNIQUE",
            "CREATE CONSTRAINT network_listing_id IF NOT EXISTS FOR (n:Listing) "
            "REQUIRE n.id IS UNIQUE",
            "CREATE INDEX network_membership_member IF NOT EXISTS "
            "FOR (n:NetworkMembership) ON (n.memberTenantId, n.status)",
            "CREATE INDEX network_membership_network IF NOT EXISTS "
            "FOR (n:NetworkMembership) ON (n.networkId, n.memberTenantId)",
            "CREATE INDEX network_grant_grantor IF NOT EXISTS "
            "FOR (n:Grant) ON (n.grantorTenantId, n.scope, n.status)",
            "CREATE INDEX network_grant_network IF NOT EXISTS FOR (n:Grant) ON (n.networkId)",
            "CREATE INDEX network_listing_source IF NOT EXISTS "
            "FOR (n:Listing) ON (n.networkId, n.sourceTenantId, n.serviceId)",
        ),
    ),
    Migration(
        "0111_projection_keys",
        statements=(
            "CREATE CONSTRAINT projection_source IF NOT EXISTS FOR (n:ProjectionSource) "
            "REQUIRE (n.tenantId, n.sourceTenantId, n.kind) IS UNIQUE",
            "CREATE CONSTRAINT projected_service IF NOT EXISTS FOR (n:ProjectedService) "
            "REQUIRE (n.tenantId, n.sourceTenantId, n.sourceServiceId) IS UNIQUE",
            "CREATE CONSTRAINT projected_location IF NOT EXISTS FOR (n:ProjectedLocation) "
            "REQUIRE (n.tenantId, n.sourceTenantId, n.sourceServiceId) IS UNIQUE",
            "CREATE CONSTRAINT projected_opening_hour IF NOT EXISTS FOR (n:ProjectedOpeningHour) "
            "REQUIRE (n.tenantId, n.sourceTenantId, n.sourceServiceId, n.position) IS UNIQUE",
            "CREATE CONSTRAINT projected_capacity IF NOT EXISTS FOR (n:ProjectedCapacity) "
            "REQUIRE (n.tenantId, n.sourceTenantId, n.sourceServiceId) IS UNIQUE",
            "CREATE CONSTRAINT projected_criteria IF NOT EXISTS FOR (n:ProjectedCriteria) "
            "REQUIRE (n.tenantId, n.sourceTenantId, n.sourceServiceId) IS UNIQUE",
            "CREATE CONSTRAINT projection_cursor IF NOT EXISTS FOR (n:ProjectionCursor) "
            "REQUIRE (n.tenantId, n.sourceTenantId, n.kind) IS UNIQUE",
            "CREATE INDEX projected_service_live IF NOT EXISTS "
            "FOR (n:ProjectedService) ON (n.tenantId, n.endedAt)",
            "CREATE INDEX projected_capacity_live IF NOT EXISTS "
            "FOR (n:ProjectedCapacity) ON (n.tenantId, n.endedAt)",
            "CREATE INDEX projected_criteria_live IF NOT EXISTS "
            "FOR (n:ProjectedCriteria) ON (n.tenantId, n.endedAt)",
        ),
    ),
)
