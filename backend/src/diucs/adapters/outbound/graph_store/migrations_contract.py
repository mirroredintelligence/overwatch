"""The contract step of the tenant schema (TEN-032, DEC-134 items 10 and 13, DEC-159 item 1).

TEN-005 added a composite key `(tenantId, key)` beside every single-property unique key a tenant
could hold, and left the old one in place so old and new code both worked. This migration drops
the eighteen superseded single-property constraints. After it, two tenants can hold the same
Concept, Communication, AuditHead, Device or any other id, and the shared schema is the schema the
generated two-tenant test already ran on (`tests/support/tenant_seed.py::contracted_container`).

It does nothing else. It drops constraints only: the six superseded range indexes
(`SUPERSEDED_INDEXES`) stay, because an index changes no answer and only the planner uses it. The
registry and global keys stay: `link_token_hash` (a token hash is looked up with no scope, DEC-131
item 5), `migration_id` and the keys of the `Tenant` and `TenantNumber` registry nodes.

Each drop is `IF EXISTS`, one statement per transaction (a schema change cannot share a
transaction, lesson L8), so a crash part way and a re-run are safe. The migration `requires` the
composite constraint that replaces each key it drops: the runner checks that all eighteen exist
before the first drop and otherwise stops with nothing dropped, so a key is never removed without
its replacement. The id is the first of TEN-032's block (0105 to 0109); it sorts after every other
migration, so a database that applied the expand step applies this one alone.
"""

from typing import Final

from diucs.adapters.outbound.graph_store.migration_types import Migration
from diucs.adapters.outbound.graph_store.migrations_tenant import COMPOSITE_CONSTRAINTS

CONTRACT_MIGRATION_ID: Final = "0105_drop_superseded_keys"

# One row per superseded key, in the order of the composite rows, from the one source.
_REPLACEMENTS: Final = tuple(
    (c.replaces, c.name) for c in COMPOSITE_CONSTRAINTS if c.replaces is not None
)

CONTRACT_MIGRATIONS: Final = (
    Migration(
        CONTRACT_MIGRATION_ID,
        statements=tuple(f"DROP CONSTRAINT {old} IF EXISTS" for old, _ in _REPLACEMENTS),
        requires=tuple(new for _, new in _REPLACEMENTS),
    ),
)
