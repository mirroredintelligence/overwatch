"""Health of the Neo4j connection (DEC-012): one bounded RETURN 1. It reports and never raises."""

import asyncio
from dataclasses import dataclass
from enum import StrEnum

from neo4j import AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.outbound.graph_store.driver import run_query
from diucs.adapters.outbound.graph_store.queries import REGISTRY, NamedQuery

PING_QUERY_ID = "Q-NEO4J-PING"
REGISTRY.register(NamedQuery(id=PING_QUERY_ID, cypher="RETURN 1 AS ok", mode="read"))


class HealthStatus(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"


@dataclass(frozen=True, slots=True)
class Health:
    status: HealthStatus
    reason: str


async def _ping(tx: AsyncManagedTransaction) -> list[dict[str, object]]:
    return await run_query(tx, PING_QUERY_ID)


async def neo4j_health(conn: Neo4jConnection, timeout: float) -> Health:
    """Report ok when Neo4j answers RETURN 1 within timeout seconds, otherwise degraded.

    The reason carries the exception's class name only, never its message or any credential.
    The driver's own retries are bounded by the timeout, so a stopped server is reported within
    about timeout seconds.
    """
    try:
        async with asyncio.timeout(timeout):
            rows = await conn.run_read(_ping)
    except TimeoutError:
        return Health(HealthStatus.DEGRADED, f"no answer from Neo4j within {timeout:g} s")
    except Exception as exc:
        return Health(HealthStatus.DEGRADED, f"Neo4j call failed: {type(exc).__name__}")
    if rows != [{"ok": 1}]:
        return Health(HealthStatus.DEGRADED, "Neo4j returned an unexpected reply")
    return Health(HealthStatus.OK, "Neo4j answered")
