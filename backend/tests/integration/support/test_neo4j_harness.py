"""Tests for the F10 Neo4j harness: write/read helpers, clean_graph, round trip, node_props.

Every test runs against the throwaway Neo4j that the session starts (DEC-008). clean_graph runs
before each test, so each test starts from an empty graph.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from neo4j import AsyncDriver

from tests.support.neo4j import count_nodes, node_props, read_tx, wipe, write_tx
from tests.support.round_trip import assert_round_trip

NAIVE_TIME = datetime(2026, 10, 24, 9, 30)
AWARE_TIME = datetime(2026, 10, 24, 9, 30, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class Sample:
    id: str
    seen_at: datetime


async def _create_probe(tx: object, probe_id: str = "a") -> None:
    await tx.run("CREATE (:Probe {id: $id})", id=probe_id)  # type: ignore[attr-defined]


async def test_write_tx_creates_a_node_that_count_nodes_sees(neo4j_driver: AsyncDriver) -> None:
    await write_tx(neo4j_driver, _create_probe)

    assert await count_nodes(neo4j_driver, "Probe") == 1


async def test_clean_graph_empties_the_graph_before_each_test(neo4j_driver: AsyncDriver) -> None:
    await write_tx(neo4j_driver, _create_probe)
    assert await count_nodes(neo4j_driver, "Probe") == 1


async def test_the_previous_test_probe_is_gone(neo4j_driver: AsyncDriver) -> None:
    assert await count_nodes(neo4j_driver, "Probe") == 0


async def test_round_trip_passes_for_a_frozen_dataclass(neo4j_driver: AsyncDriver) -> None:
    async def save(tx: object) -> None:
        await tx.run(  # type: ignore[attr-defined]
            "CREATE (:Probe {id: $id, seenAt: datetime($seen)})",
            id="a",
            seen=AWARE_TIME.isoformat(),
        )

    async def load(tx: object) -> Sample:
        result = await tx.run(  # type: ignore[attr-defined]
            "MATCH (p:Probe {id: 'a'}) RETURN p.id AS id, p.seenAt AS seen_at"
        )
        record = await result.single()
        assert record is not None
        return Sample(id=record["id"], seen_at=record["seen_at"].to_native())

    await assert_round_trip(neo4j_driver, save, load, Sample(id="a", seen_at=AWARE_TIME))


async def test_round_trip_fails_when_load_returns_a_naive_datetime(
    neo4j_driver: AsyncDriver,
) -> None:
    async def save(tx: object) -> None:
        await _create_probe(tx, "a")

    async def load(tx: object) -> Sample:
        return Sample(id="a", seen_at=NAIVE_TIME)

    with pytest.raises(AssertionError, match="UTC"):
        await assert_round_trip(neo4j_driver, save, load, Sample(id="a", seen_at=NAIVE_TIME))


async def test_node_props_returns_the_properties_of_the_one_match(
    neo4j_driver: AsyncDriver,
) -> None:
    await write_tx(neo4j_driver, _create_probe)

    props = await node_props(neo4j_driver, "Probe", id="a")

    assert props == {"id": "a"}


async def test_node_props_names_the_count_when_two_nodes_match(neo4j_driver: AsyncDriver) -> None:
    async def create_two(tx: object) -> None:
        await tx.run("CREATE (:Probe {id: 'a'}), (:Probe {id: 'a'})")  # type: ignore[attr-defined]

    await write_tx(neo4j_driver, create_two)

    with pytest.raises(AssertionError, match="2"):
        await node_props(neo4j_driver, "Probe", id="a")


async def test_constraint_from_migrations_survives_wipe(neo4j_driver: AsyncDriver) -> None:
    await write_tx(neo4j_driver, _create_probe)
    await wipe(neo4j_driver)

    async def constraint_names(tx: object) -> list[str]:
        result = await tx.run(  # type: ignore[attr-defined]
            "SHOW CONSTRAINTS YIELD name WHERE name = 'resource_id' RETURN name"
        )
        return [record["name"] async for record in result]

    assert await read_tx(neo4j_driver, constraint_names) == ["resource_id"]
    assert await count_nodes(neo4j_driver, "Probe") == 0
