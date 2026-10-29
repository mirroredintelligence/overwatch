"""Integration tests for the protected text store (P20), against the F10 harness Neo4j.

The text used here is a synthetic sample. It must not appear on any node but the protected one.
"""

from typing import Any

import pytest
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.protected_text_store import Neo4jProtectedTextStore
from diucs.domain.errors import ValidationFailed
from tests.support.neo4j import read_tx, write_tx

pytestmark = pytest.mark.asyncio(loop_scope="session")

SAMPLE = "Board showed accepting but they were closed"


async def _put(driver: AsyncDriver, kind: str, about: str, text: str) -> str:
    async def work(tx: AsyncManagedTransaction) -> str:
        return await Neo4jProtectedTextStore(tx).put(kind, about, text)

    return await write_tx(driver, work)


async def _get(driver: AsyncDriver, handle: str) -> str | None:
    return await read_tx(driver, lambda tx: Neo4jProtectedTextStore(tx).get(handle))


async def _scalar(driver: AsyncDriver, cypher: str, **params: Any) -> Any:
    async def work(tx: AsyncManagedTransaction) -> Any:
        result = await tx.run(cypher, params)
        record = await result.single()
        return record[0] if record is not None else None

    return await read_tx(driver, work)


async def test_a_text_is_stored_under_a_handle_and_read_back(neo4j_driver: AsyncDriver) -> None:
    handle = await _put(neo4j_driver, "safety-concern", "task-1", SAMPLE)

    assert len(handle) >= 22
    assert await _get(neo4j_driver, handle) == SAMPLE
    assert await _get(neo4j_driver, "nope") is None


async def test_a_text_over_280_characters_is_refused(neo4j_driver: AsyncDriver) -> None:
    with pytest.raises(ValidationFailed):
        await _put(neo4j_driver, "safety-concern", "task-1", "a" * 281)


async def test_the_protected_node_has_no_relationships_and_no_other_node_holds_the_text(
    neo4j_driver: AsyncDriver,
) -> None:
    await _put(neo4j_driver, "safety-concern", "task-1", SAMPLE)

    relationships = await _scalar(
        neo4j_driver, "MATCH (:ProtectedText)-[r]-() RETURN count(r) AS n"
    )
    assert relationships == 0
    holders = await _scalar(
        neo4j_driver,
        "MATCH (n) WHERE NOT n:Protected AND any(k IN keys(n) "
        "WHERE toString(n[k]) CONTAINS 'they were closed') RETURN count(n) AS n",
    )
    assert holders == 0
