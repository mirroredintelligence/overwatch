"""The shared postcode points on Neo4j (DEC-1329): one registry node per postcode, held once for
every tenant, because postcodes and their points are public.

The read is a global statement (`Q-POSTCODE-POINTS-OF`), pinned by digest: it matches registry nodes
only and names no tenant. The write is the platform's and lives in `tenant_registry.py`, the only
module that runs platform statements; this adapter delegates it there.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from neo4j import AsyncManagedTransaction

from overwatch.adapters.outbound.graph_store.connection import Neo4jConnection
from overwatch.adapters.outbound.graph_store.driver import run_global_query
from overwatch.adapters.outbound.graph_store.queries import REGISTRY, NamedQuery
from overwatch.adapters.outbound.graph_store.tenant_registry import Neo4jPostcodePoints
from overwatch.application.ports.outbound.postcode_directory import DirectoryPostcode

_POINTS_OF = NamedQuery(
    id="Q-POSTCODE-POINTS-OF",
    cypher=(
        "MATCH (p:PostcodePoint {district: $district}) "
        "RETURN p.postcode AS postcode, p.lat AS lat, p.lon AS lon ORDER BY p.postcode"
    ),
    mode="read",
    scope="global",
)
REGISTRY.register(_POINTS_OF)


class Neo4jPostcodePointStore:
    """The `PostcodePointStore` port: the platform write delegated to `tenant_registry.py`, and the
    global read of a district's points."""

    def __init__(self, connection: Neo4jConnection, points: Neo4jPostcodePoints) -> None:
        self._connection = connection
        self._points = points

    async def upsert(self, points: Sequence[DirectoryPostcode]) -> int:
        return await self._points.upsert(points, datetime.now().astimezone())

    async def of_district(self, district: str) -> list[tuple[str, float, float]]:
        async def work(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
            return await run_global_query(tx, _POINTS_OF, district=district)

        rows = await self._connection.run_read(work)
        return [(row["postcode"], row["lat"], row["lon"]) for row in rows]
