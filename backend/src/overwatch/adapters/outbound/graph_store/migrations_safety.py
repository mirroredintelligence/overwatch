"""Migration of the safety counter (U41): one composite uniqueness constraint.

0070: a safety counter is unique within its tenant (tenantId, counterId). The counter is advanced by
one MERGE in the caller's unit, so the constraint is what refuses a second counter created by two
racing units. One schema statement with IF NOT EXISTS, so a re-run changes nothing (lesson L8).
The ids 0070 to 0074 are the build wave W2D's block.
"""

from typing import Final

from diucs.adapters.outbound.graph_store.migration_types import Migration

SAFETY_MIGRATIONS: Final[tuple[Migration, ...]] = (
    Migration(
        "0070_safety_counter_id",
        statements=(
            "CREATE CONSTRAINT safety_counter_id IF NOT EXISTS FOR (n:SafetyCounter) "
            "REQUIRE (n.tenantId, n.counterId) IS UNIQUE",
        ),
    ),
)
