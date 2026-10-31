"""Migrations of the platform's own records (TEN-075): the platform audit chain and the
support-access tickets.

Migration 0190 (the first id of the block 0190 to 0194 given to build wave 9, bundle W9C) makes the
keys of the platform's records unique and indexes the reads the two sides of a ticket make. Like the
registry, these nodes carry no `tenantId` (DEC-132): they are the platform's, reached only by
platform statements (`PLATFORM_QUERY_IDS`), and `REGISTRY_LABELS` lists their labels so that the
invariant check (TEN-031) does not count them as nodes that lost their tenant.

- `PlatformAuditHead.id`: one head for the platform chain.
- `PlatformAuditEntry.seq`: a link has one place in the chain, so two appends that read the same
  head cannot both write (the head is also compared and set).
- `SupportAccessTicket.id`: a ticket has one record.
- Indexes on `forTenant` and `requestedBy`: the tenant's administrator lists by the first, the
  support person by the second.

One schema statement each (lesson L8), idempotent (`IF NOT EXISTS`), fixed text written out in full
(DEC-142 item 1). Expand only: no label existed before, so nothing is dropped and no data written.
"""

from typing import Final

from diucs.adapters.outbound.graph_store.migration_types import Migration

PLATFORM_MIGRATIONS: Final[tuple[Migration, ...]] = (
    Migration(
        "0190_platform_records",
        statements=(
            "CREATE CONSTRAINT platform_audit_head_id IF NOT EXISTS "
            "FOR (n:PlatformAuditHead) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT platform_audit_seq IF NOT EXISTS "
            "FOR (n:PlatformAuditEntry) REQUIRE n.seq IS UNIQUE",
            "CREATE CONSTRAINT support_ticket_id IF NOT EXISTS "
            "FOR (n:SupportAccessTicket) REQUIRE n.id IS UNIQUE",
            "CREATE INDEX support_ticket_tenant IF NOT EXISTS "
            "FOR (n:SupportAccessTicket) ON (n.forTenant, n.requestedAt)",
            "CREATE INDEX support_ticket_principal IF NOT EXISTS "
            "FOR (n:SupportAccessTicket) ON (n.requestedBy, n.requestedAt)",
        ),
    ),
)
