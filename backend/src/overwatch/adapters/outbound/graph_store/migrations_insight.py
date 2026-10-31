"""Migrations of the browser-insight counters (W9F): the composite keys, then the indexes.

- 0195: a composite uniqueness key, with the tenant first, on each of the eight labels the
  counters write (the five aggregate labels of O08, the two new ones, and the session marker). The
  counters are written by MERGE, and a MERGE on a key with no constraint can create two nodes when
  two batches meet (lessons L90, L122); with the constraint the second waits and matches. The
  O08 known issue (no uniqueness on the five labels) is closed here. The friction key gains the
  route (a page-level friction is per route; a control's has an empty one).
- 0196: two indexes. The marker clean-up looks markers up by day; the pipeline reads a tenant's
  outbox by status.

Each statement is one schema statement (lesson L8) and idempotent (IF NOT EXISTS). Ids 0195 and
0196 are this area's block.
"""

from typing import Final

from diucs.adapters.outbound.graph_store.migration_types import Migration

INSIGHT_MIGRATIONS: Final[tuple[Migration, ...]] = (
    Migration(
        "0195_insight_keys",
        statements=(
            "CREATE CONSTRAINT insight_funnel_daily IF NOT EXISTS FOR (n:FunnelDaily) "
            "REQUIRE (n.tenantId, n.funnel, n.step, n.date, n.role, n.channel, n.device) "
            "IS UNIQUE",
            "CREATE CONSTRAINT insight_friction_daily IF NOT EXISTS FOR (n:FrictionDaily) "
            "REQUIRE (n.tenantId, n.date, n.elementId, n.kind, n.role, n.device, n.route) "
            "IS UNIQUE",
            "CREATE CONSTRAINT insight_usage_daily IF NOT EXISTS FOR (n:ElementUsageDaily) "
            "REQUIRE (n.tenantId, n.date, n.elementId, n.role, n.device) IS UNIQUE",
            "CREATE CONSTRAINT insight_route_daily IF NOT EXISTS FOR (n:RouteDaily) "
            "REQUIRE (n.tenantId, n.date, n.route, n.role, n.device) IS UNIQUE",
            "CREATE CONSTRAINT insight_query_daily IF NOT EXISTS FOR (n:QueryStatDaily) "
            "REQUIRE (n.tenantId, n.date, n.queryId) IS UNIQUE",
            "CREATE CONSTRAINT insight_measure_daily IF NOT EXISTS FOR (n:MeasureDaily) "
            "REQUIRE (n.tenantId, n.date, n.measure, n.route, n.device, n.release) IS UNIQUE",
            "CREATE CONSTRAINT insight_release_daily IF NOT EXISTS FOR (n:ReleaseDaily) "
            "REQUIRE (n.tenantId, n.date, n.release) IS UNIQUE",
            "CREATE CONSTRAINT insight_tally_seen IF NOT EXISTS FOR (n:TallySeen) "
            "REQUIRE (n.tenantId, n.key) IS UNIQUE",
        ),
    ),
    Migration(
        "0196_insight_indexes",
        statements=(
            "CREATE INDEX insight_tally_seen_date IF NOT EXISTS FOR (n:TallySeen) "
            "ON (n.tenantId, n.date)",
            "CREATE INDEX insight_outbox_status IF NOT EXISTS FOR (n:OutboxMessage) "
            "ON (n.tenantId, n.status)",
        ),
    ),
)
