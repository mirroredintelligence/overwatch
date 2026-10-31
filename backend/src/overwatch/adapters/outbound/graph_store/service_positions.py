"""The site position of each service, read from its Location (U12, Q-SVC-POSITIONS).

A service's Location is linked by LOCATION, and the position is the Location's latitude and
longitude, as the resource store writes them (G04). Every node the statement matches carries
`tenantId: $tenant`, so another tenant's Location is never returned. A service with more than one
Location gives the first one by id; a service with none is left out.
"""

from collections.abc import Sequence
from typing import Final

from diucs.adapters.outbound.graph_store.driver import ScopedTx, run_query
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

_SERVICE_COVERAGE: Final = NamedQuery(
    id="Q-SVC-COVERAGE",
    cypher=(
        "MATCH (s:HealthcareService {tenantId: $tenant})-[:COVERAGE_AREA]->"
        "(l:Location {tenantId: $tenant}) "
        "WHERE s.id IN $ids AND l.name IS NOT NULL "
        "RETURN s.id AS id, l.name AS district ORDER BY s.id, l.name"
    ),
    mode="read",
    scenario=SCENARIOS["Q-SVC-COVERAGE"],
)

for _query in (_SERVICE_POSITIONS, _SERVICE_COVERAGE):
    if _query.id not in REGISTRY.ids():
        REGISTRY.register(_query)


class Neo4jServicePositions:
    """Service positions inside the unit of work's transaction (DEC-012)."""

    def __init__(self, tx: ScopedTx) -> None:
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

    async def coverage_districts(self, service_ids: Sequence[str]) -> dict[str, tuple[str, ...]]:
        if not service_ids:
            return {}
        rows = await run_query(self._tx, REGISTRY.get("Q-SVC-COVERAGE"), ids=list(service_ids))
        found: dict[str, list[str]] = {}
        for row in rows:
            found.setdefault(str(row["id"]), []).append(str(row["district"]))
        return {service: tuple(districts) for service, districts in found.items()}
