"""Migrations of the protected text and service move stores (P20).

Two composite uniqueness constraints, each one schema statement (lesson L8: a schema statement runs
in its own transaction) and idempotent (IF NOT EXISTS), so a re-run changes nothing:

- 0040: a protected text's handle is unique within its tenant (the handle is a random 128-bit token,
  so a collision is negligible, but nothing refused one before this).
- 0041: a service move's id (the property moveId) is unique within its tenant. The add guard checks
  for an existing id before it writes; the constraint refuses a racing second write as well.

The ids are the ones the build wave was given for this area (0040 to 0044).
"""

from typing import Final

from diucs.adapters.outbound.graph_store.migration_types import Migration

PROTECTED_MIGRATIONS: Final[tuple[Migration, ...]] = (
    Migration(
        "0040_protected_text_handle",
        statements=(
            "CREATE CONSTRAINT protected_text_handle IF NOT EXISTS FOR (n:ProtectedText) "
            "REQUIRE (n.tenantId, n.handle) IS UNIQUE",
        ),
    ),
    Migration(
        "0041_service_move_id",
        statements=(
            "CREATE CONSTRAINT service_move_id IF NOT EXISTS FOR (n:ServiceMove) "
            "REQUIRE (n.tenantId, n.moveId) IS UNIQUE",
        ),
    ),
)
