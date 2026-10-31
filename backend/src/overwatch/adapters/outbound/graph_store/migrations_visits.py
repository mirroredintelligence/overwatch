"""Migrations of the visit offers (DEC-1309): two composite uniqueness constraints.

- 0200: an offer's id is unique within its tenant (`VisitOffer`), so two offers cannot share an id
  and a tenant's offers never collide with another tenant's.
- 0201: a practitioner has one settings node within the tenant (`VisitSettings`); its write is a
  MERGE on (practitionerId, tenantId), and the constraint makes a racing second MERGE wait and match
  (lessons L90, L122).

Each is one schema statement (lesson L8) and idempotent (IF NOT EXISTS). Ids 0200 and 0201 are this
area's block; every other id on the branch was checked before they were chosen (lesson L68).
"""

from typing import Final

from overwatch.adapters.outbound.graph_store.migration_types import Migration

VISIT_MIGRATIONS: Final[tuple[Migration, ...]] = (
    Migration(
        "0200_visit_offer_id",
        statements=(
            "CREATE CONSTRAINT visit_offer_id IF NOT EXISTS FOR (n:VisitOffer) "
            "REQUIRE (n.tenantId, n.id) IS UNIQUE",
        ),
    ),
    Migration(
        "0201_visit_settings_practitioner",
        statements=(
            "CREATE CONSTRAINT visit_settings_practitioner IF NOT EXISTS FOR (n:VisitSettings) "
            "REQUIRE (n.tenantId, n.practitionerId) IS UNIQUE",
        ),
    ),
)
