"""Health of the Neo4j connection (DEC-012). STUB: red commit, bodies not implemented."""

from dataclasses import dataclass
from enum import StrEnum

from diucs.adapters.outbound.graph_store.connection import Neo4jConnection


class HealthStatus(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"


@dataclass(frozen=True, slots=True)
class Health:
    status: HealthStatus
    reason: str


async def neo4j_health(conn: Neo4jConnection, timeout: float) -> Health:
    raise NotImplementedError
