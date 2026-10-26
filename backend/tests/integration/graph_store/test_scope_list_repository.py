"""Integration tests for the scope list on Neo4j (P13).

The scope list is one List node with ENTRY relationships to HealthcareService nodes. A service that
is not written yet is created as a minimal inactive service. The race tests hold one
transaction open, or race 16 writers, to prove the interleaving (lessons L77, L90, L94). Values are
synthetic; there is no patient data.
"""

import asyncio
from datetime import date
from typing import Any

import pytest
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.adapters.outbound.graph_store.scope_list_repository import Neo4jScopeListRepository
from diucs.adapters.outbound.graph_store.service_repository import codeable_to_fhir
from diucs.domain.codes import ScopeFlag, ServiceCategory
from diucs.domain.errors import Conflict
from diucs.domain.model.registration import ScopeEntry
from tests.support.neo4j import count_nodes, node_props, read_tx, write_tx
from tests.support.round_trip import assert_round_trip

pytestmark = pytest.mark.asyncio(loop_scope="session")

SDEC = "svc-sdec-1"
WEST = "svc-ucr-west"
DAY = date(2026, 10, 25)


def _repo(tx: AsyncManagedTransaction) -> Neo4jScopeListRepository:
    return Neo4jScopeListRepository(tx, ResourceStore(tx))


def _sdec(flag: ScopeFlag = ScopeFlag.IN_PILOT, reason: str = "") -> ScopeEntry:
    return ScopeEntry(
        service_id=SDEC,
        name="SDEC pilot",
        category=ServiceCategory.SAME_DAY_EMERGENCY_CARE,
        flag=flag,
        date=DAY,
        reason=reason,
    )


async def _seed_active_service(driver: AsyncDriver) -> None:
    """UCR West, an active service the scope list must never overwrite."""

    async def work(tx: AsyncManagedTransaction) -> None:
        resource = {
            "resourceType": "HealthcareService",
            "id": WEST,
            "active": True,
            "name": "UCR West",
            "category": codeable_to_fhir(ServiceCategory.URGENT_COMMUNITY_RESPONSE),
        }
        await ResourceStore(tx).put(resource, None)

    await write_tx(driver, work)


async def _run(driver: AsyncDriver, *entries: ScopeEntry) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        for entry in entries:
            await _repo(tx).save_entry(entry)

    await write_tx(driver, work)


async def _read(driver: AsyncDriver, step: Any) -> Any:
    return await read_tx(driver, lambda tx: step(_repo(tx)))


async def _rows(driver: AsyncDriver, cypher: str, **params: Any) -> list[dict[str, Any]]:
    async def work(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        result = await tx.run(cypher, **params)
        return await result.data()

    return await read_tx(driver, work)


async def test_an_entry_for_a_service_not_yet_written_creates_one_inactive_service(
    neo4j_driver: AsyncDriver,
) -> None:
    await _run(neo4j_driver, _sdec(ScopeFlag.IN_PILOT))

    props = await node_props(neo4j_driver, "HealthcareService", id=SDEC)
    assert props["active"] is False
    assert props["name"] == "SDEC pilot"
    assert await count_nodes(neo4j_driver, "HealthcareService") == 1
    rows = await _rows(
        neo4j_driver,
        "MATCH (:List)-[e:ENTRY]->(:HealthcareService {id: $id}) RETURN e.flag AS flag",
        id=SDEC,
    )
    assert rows == [{"flag": "in-pilot"}]


async def test_saving_the_same_entry_again_updates_the_relationship_not_a_second_one(
    neo4j_driver: AsyncDriver,
) -> None:
    await _run(neo4j_driver, _sdec(ScopeFlag.IN_PILOT))
    await _run(neo4j_driver, _sdec(ScopeFlag.LATER, reason="Waiting for the lead"))

    rows = await _rows(
        neo4j_driver,
        "MATCH (:List)-[e:ENTRY]->(:HealthcareService {id: $id}) "
        "RETURN e.flag AS flag, e.reason AS reason",
        id=SDEC,
    )
    assert rows == [{"flag": "later", "reason": "Waiting for the lead"}]
    assert await count_nodes(neo4j_driver, "HealthcareService") == 1


async def test_saving_an_entry_for_an_existing_active_service_leaves_it_untouched(
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed_active_service(neo4j_driver)
    renamed = ScopeEntry(
        service_id=WEST,
        name="Renamed by the list",
        category=ServiceCategory.INPATIENT_BEDS,
        flag=ScopeFlag.IN_PILOT,
        date=DAY,
    )

    await _run(neo4j_driver, renamed)

    props = await node_props(neo4j_driver, "HealthcareService", id=WEST)
    assert props["name"] == "UCR West"
    assert props["active"] is True
    entry = await _read(neo4j_driver, lambda repo: repo.get_entry(WEST))
    assert entry is not None
    assert entry.name == "UCR West"
    assert entry.category is ServiceCategory.URGENT_COMMUNITY_RESPONSE
    assert entry.flag is ScopeFlag.IN_PILOT


async def test_entries_are_sorted_by_name_and_an_unknown_service_has_no_entry(
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed_active_service(neo4j_driver)
    await _run(neo4j_driver, _sdec(ScopeFlag.IN_PILOT))

    entries = await _read(neo4j_driver, lambda repo: repo.entries())

    assert [entry.name for entry in entries] == ["SDEC pilot", "UCR West"]
    assert await _read(neo4j_driver, lambda repo: repo.get_entry("svc-unknown")) is None


async def test_an_entry_round_trips_with_its_flag_date_and_reason(
    neo4j_driver: AsyncDriver,
) -> None:
    entry = _sdec(ScopeFlag.OUT_OF_SCOPE, reason="Outside the pilot area")

    async def save(tx: AsyncManagedTransaction) -> None:
        await _repo(tx).save_entry(entry)

    async def load(tx: AsyncManagedTransaction) -> ScopeEntry | None:
        return await _repo(tx).get_entry(SDEC)

    await assert_round_trip(neo4j_driver, save, load, entry)


async def test_a_second_save_for_a_service_waits_for_a_held_save_and_leaves_one_entry(
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed_active_service(neo4j_driver)
    session = neo4j_driver.session()
    held = await session.begin_transaction()
    try:
        await _repo(held).save_entry(
            ScopeEntry(
                service_id=WEST,
                name="UCR West",
                category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
                flag=ScopeFlag.IN_PILOT,
                date=DAY,
            )
        )
        racer = asyncio.create_task(
            write_tx(
                neo4j_driver,
                lambda tx: _repo(tx).save_entry(
                    ScopeEntry(
                        service_id=WEST,
                        name="UCR West",
                        category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
                        flag=ScopeFlag.LATER,
                        date=DAY,
                    )
                ),
            )
        )
        done, _ = await asyncio.wait({racer}, timeout=1.0)
        assert not done, "the second save must wait for the held write on the scope list"
    finally:
        await held.commit()
        await session.close()
    await racer

    rows = await _rows(
        neo4j_driver,
        "MATCH (:List)-[e:ENTRY]->(:HealthcareService {id: $id}) RETURN e.flag AS flag",
        id=WEST,
    )
    assert rows == [{"flag": "later"}]


async def test_sixteen_racing_first_saves_for_one_service_leave_one_entry(
    neo4j_driver: AsyncDriver,
) -> None:
    await _run(neo4j_driver, _sdec(ScopeFlag.LATER))  # the list exists before the race
    racers = [
        asyncio.create_task(write_tx(neo4j_driver, lambda tx: _repo(tx).save_entry(_sdec())))
        for _ in range(16)
    ]
    outcomes = await asyncio.gather(*racers, return_exceptions=True)

    assert all(outcome is None or isinstance(outcome, Conflict) for outcome in outcomes)
    assert await count_nodes(neo4j_driver, "HealthcareService") == 1
    rows = await _rows(
        neo4j_driver,
        "MATCH (:List)-[e:ENTRY]->(:HealthcareService {id: $id}) RETURN count(e) AS entries",
        id=SDEC,
    )
    assert rows == [{"entries": 1}]


async def test_sixteen_racing_creations_of_the_list_leave_one_list(
    neo4j_driver: AsyncDriver,
) -> None:
    racers = [
        asyncio.create_task(write_tx(neo4j_driver, lambda tx: _repo(tx).save_entry(_sdec())))
        for _ in range(16)
    ]
    outcomes = await asyncio.gather(*racers, return_exceptions=True)

    assert any(outcome is None for outcome in outcomes)
    assert all(outcome is None or isinstance(outcome, Conflict) for outcome in outcomes)
    assert await count_nodes(neo4j_driver, "List") == 1
    assert await count_nodes(neo4j_driver, "HealthcareService") == 1
