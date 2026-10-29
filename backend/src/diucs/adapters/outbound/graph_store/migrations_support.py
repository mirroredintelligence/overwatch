"""Migrations of the support-access records (O06): two composite uniqueness constraints.

- 0045: a session's id is unique within its tenant (`UiSession`). The ensure statement is a MERGE on
  (id, tenantId); without the constraint two first writes of one session could create two nodes
  (lesson L90). With it, a racing second MERGE waits and matches (lesson L122).
- 0046: a support code's hash is unique within its tenant (`SupportCode`). add_code checks before it
  writes; the constraint refuses a racing second write as well, and the adapter turns that refusal
  into Conflict.

Each is one schema statement (lesson L8: a schema statement runs in its own transaction) and
idempotent (IF NOT EXISTS), so a re-run changes nothing. Ids 0045 to 0049 are reserved for this area
(the build wave gave O06 these ids); every other id on main and on every branch is checked before a
new one is added (lesson L68).
"""

from typing import Final

from diucs.adapters.outbound.graph_store.migration_types import Migration

SUPPORT_MIGRATIONS: Final[tuple[Migration, ...]] = (
    Migration(
        "0045_support_session_id",
        statements=(
            "CREATE CONSTRAINT support_session_id IF NOT EXISTS FOR (n:UiSession) "
            "REQUIRE (n.tenantId, n.id) IS UNIQUE",
        ),
    ),
    Migration(
        "0046_support_code_hash",
        statements=(
            "CREATE CONSTRAINT support_code_hash IF NOT EXISTS FOR (n:SupportCode) "
            "REQUIRE (n.tenantId, n.codeHash) IS UNIQUE",
        ),
    ),
)
