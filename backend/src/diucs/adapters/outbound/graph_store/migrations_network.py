"""Migrations of the network registry and projections (TEN-051; TEN-053 adds its own).

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
)
