"""The site position of each service, read from its Location (U12, Q-SVC-POSITIONS).

A service's Location is linked by LOCATION, and the position is the Location's latitude and
longitude, as the resource store writes them (G04). Every node the statement matches carries
`tenantId: $tenant`, so another tenant's Location is never returned. A service with more than one
Location gives the first one by id; a service with none is left out.
"""

from collections.abc import Sequence
from typing import Final

from neo4j import AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.driver import run_query
from diucs.adapters.outbound.graph_store.queries import REGISTRY, NamedQuery
from diucs.adapters.outbound.graph_store.service_scenarios import SCENARIOS
from diucs.application.ports.outbound.geo import LatLon

_SERVICE_POSITIONS: Final = NamedQuery(
    id="Q-SVC-POSITIONS",
    cypher=(
        "MATCH (s:HealthcareService {tenantId: $tenant})-[:LOCATION]->"
        "(l:Location {tenantId: $tenant}) "
        "WHERE s.id IN $ids AND l.positionLatitude IS NOT NULL AND l.positionLongitude IS NOT NULL "
        "RETURN s.id AS id, s.name AS name, l.positionLatitude AS lat, l.positionLongitude AS lon "
        "ORDER BY s.id, l.id"
    ),
    mode="read",
    scenario=SCENARIOS["Q-SVC-POSITIONS"],
)

if _SERVICE_POSITIONS.id not in REGISTRY.ids():
    REGISTRY.register(_SERVICE_POSITIONS)


class Neo4jServicePositions:
    """Service positions inside the unit of work's transaction (DEC-012)."""

    def __init__(self, tx: AsyncManagedTransaction) -> None:
        self._tx = tx

    async def get_many(self, service_ids: Sequence[str]) -> dict[str, LatLon]:
        if not service_ids:
            return {}
        rows = await run_query(self._tx, REGISTRY.get("Q-SVC-POSITIONS"), ids=list(service_ids))
        positions: dict[str, LatLon] = {}
        for row in rows:
            service_id = str(row["id"])
            if service_id not in positions:
                positions[service_id] = LatLon(lat=float(row["lat"]), lon=float(row["lon"]))
        return positions
