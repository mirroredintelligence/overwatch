"""Integration tests for the criteria repository (P04).

They run against the throwaway Neo4j that the F10 harness starts for the pytest session (DEC-008).
Every write is one committed transaction and every read is a fresh session, so the tests assert on
what was really stored. The two race tests hold one transaction open and start a second writer
while it is held (lesson L94), so they prove the interleaving and not a timing. Values are
synthetic; there is no patient data.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any

import pytest
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.criteria_repository import (
    Neo4jCriteriaRepository,
    criteria_to_fhir,
)
from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.adapters.outbound.graph_store.service_repository import Neo4jServiceRepository
from diucs.domain.codes import CriteriaStatus
from diucs.domain.errors import Conflict, NotFound, ValidationFailed
from diucs.domain.model.criteria import ServiceCriteria
from tests.support.neo4j import count_nodes, node_props, read_tx, write_tx
from tests.support.round_trip import assert_round_trip
from tests.unit.adapters.outbound.graph_store.test_criteria_mapping import UCR_WEST_V3
from tests.unit.adapters.outbound.graph_store.test_service_repository import UCR_WEST

pytestmark = pytest.mark.asyncio(loop_scope="session")

SERVICE = "svc-ucr-west"
V3_ID = UCR_WEST_V3.id

V4_PENDING = replace(
    UCR_WEST_V3,
    id="crit-ucr-west-v4",
    version=4,
    status=CriteriaStatus.PENDING_APPROVAL,
    supersedes_id=V3_ID,
)
V4_CURRENT = replace(V4_PENDING, status=CriteriaStatus.CURRENT)
V3_SUPERSEDED = replace(UCR_WEST_V3, status=CriteriaStatus.SUPERSEDED)

Step = Callable[[Neo4jCriteriaRepository], Awaitable[Any]]


def _repo(tx: AsyncManagedTransaction) -> Neo4jCriteriaRepository:
    return Neo4jCriteriaRepository(tx, ResourceStore(tx))


async def _seed_service(driver: AsyncDriver) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        await Neo4jServiceRepository(tx, ResourceStore(tx)).save(UCR_WEST)

    await write_tx(driver, work)


async def _run(driver: AsyncDriver, *steps: Step) -> None:
    """Run the steps in one committed write transaction, in order."""

    async def work(tx: AsyncManagedTransaction) -> None:
        repo = _repo(tx)
        for step in steps:
            await step(repo)

    await write_tx(driver, work)


async def _read(
    driver: AsyncDriver, step: Callable[[Neo4jCriteriaRepository], Awaitable[Any]]
) -> Any:
    return await read_tx(driver, lambda tx: step(_repo(tx)))


async def _rows(driver: AsyncDriver, cypher: str, **params: Any) -> list[dict[str, Any]]:
    async def work(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        result = await tx.run(cypher, **params)
        return await result.data()

    return await read_tx(driver, work)


async def test_ucr_west_v3_round_trips_and_is_stored_as_graph_properties(
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed_service(neo4j_driver)
    await assert_round_trip(
        neo4j_driver,
        lambda tx: _repo(tx).add(UCR_WEST_V3),
        lambda tx: _repo(tx).get(V3_ID),
        UCR_WEST_V3,
    )
    props = await node_props(neo4j_driver, "ServiceCriteria", id=V3_ID)
    assert props["postcodeDistricts"] == ["DT1", "DT2", "DT3", "DT4"]
    stored = await read_tx(neo4j_driver, lambda tx: _stored_basic(tx, V3_ID))
    assert stored == criteria_to_fhir(UCR_WEST_V3)


async def _stored_basic(tx: AsyncManagedTransaction, basic_id: str) -> dict[str, Any] | None:
    resource = await ResourceStore(tx).get("Basic", basic_id)
    if resource is None:
        return None
    resource.pop("meta", None)
    return resource


async def test_saving_v3_as_current_points_the_service_at_it(neo4j_driver: AsyncDriver) -> None:
    await _seed_service(neo4j_driver)
    await _run(neo4j_driver, lambda repo: repo.add(UCR_WEST_V3))
    rows = await _rows(
        neo4j_driver,
        "MATCH (:HealthcareService {id: $service})-[:CURRENT_CRITERIA]->(c) "
        "RETURN c.version AS version",
        service=SERVICE,
    )
    assert rows == [{"version": 3}]


async def test_a_second_current_version_is_a_conflict_and_writes_nothing(
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed_service(neo4j_driver)
    await _run(neo4j_driver, lambda repo: repo.add(UCR_WEST_V3))
    with pytest.raises(Conflict):
        await _run(neo4j_driver, lambda repo: repo.add(V4_CURRENT))
    assert await count_nodes(neo4j_driver, "ServiceCriteria") == 1
    assert await _read(neo4j_driver, lambda repo: repo.current_for_service(SERVICE)) == UCR_WEST_V3


async def test_superseding_then_making_v4_current_moves_the_link_and_keeps_history(
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed_service(neo4j_driver)
    await _run(neo4j_driver, lambda repo: repo.add(UCR_WEST_V3))
    await _run(neo4j_driver, lambda repo: repo.add(V4_PENDING))
    await _run(neo4j_driver, lambda repo: repo.save(V3_SUPERSEDED))
    # Between the two steps no version is current, so the service has no link.
    assert await _read(neo4j_driver, lambda repo: repo.current_for_service(SERVICE)) is None
    assert (
        await _rows(
            neo4j_driver,
            "MATCH (:HealthcareService {id: $service})-[:CURRENT_CRITERIA]->(c) RETURN c.id AS id",
            service=SERVICE,
        )
        == []
    )
    await _run(neo4j_driver, lambda repo: repo.save(V4_CURRENT))
    assert await _read(neo4j_driver, lambda repo: repo.current_for_service(SERVICE)) == V4_CURRENT
    links = await _rows(
        neo4j_driver,
        "MATCH (:HealthcareService {id: $service})-[:CURRENT_CRITERIA]->(c) RETURN c.id AS id",
        service=SERVICE,
    )
    assert links == [{"id": V4_PENDING.id}]
    supersedes = await _rows(
        neo4j_driver,
        "MATCH (:ServiceCriteria {id: $new})-[:SUPERSEDES]->(old:ServiceCriteria) "
        "RETURN old.id AS id",
        new=V4_PENDING.id,
    )
    assert supersedes == [{"id": V3_ID}]
    history = await _read(neo4j_driver, lambda repo: repo.history(SERVICE))
    assert [version.id for version in history] == [V4_PENDING.id, V3_ID]
    assert [version.status for version in history] == [
        CriteriaStatus.CURRENT,
        CriteriaStatus.SUPERSEDED,
    ]


async def test_repeated_needs_share_their_concept_nodes(neo4j_driver: AsyncDriver) -> None:
    await _seed_service(neo4j_driver)
    await _run(neo4j_driver, lambda repo: repo.add(UCR_WEST_V3))
    before = await count_nodes(neo4j_driver, "Concept")
    await _run(neo4j_driver, lambda repo: repo.add(V4_PENDING))
    assert await count_nodes(neo4j_driver, "Concept") == before


async def test_current_for_services_skips_services_without_criteria(
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed_service(neo4j_driver)
    await _run(neo4j_driver, lambda repo: repo.add(UCR_WEST_V3))
    found = await _read(neo4j_driver, lambda repo: repo.current_for_services([SERVICE, "svc-none"]))
    assert found == {SERVICE: UCR_WEST_V3}
    assert await _read(neo4j_driver, lambda repo: repo.get("missing")) is None


async def test_a_basic_that_is_not_a_criteria_version_is_not_read_as_one(
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed_service(neo4j_driver)

    async def write_flag(tx: AsyncManagedTransaction) -> None:
        await ResourceStore(tx).put(
            {
                "resourceType": "Basic",
                "id": "flag-suspended",
                "subject": {"reference": f"HealthcareService/{SERVICE}"},
                "status": "active",
            },
            None,
        )

    await write_tx(neo4j_driver, write_flag)
    assert await _read(neo4j_driver, lambda repo: repo.get("flag-suspended")) is None


async def test_adding_for_an_unknown_service_is_not_found_and_writes_nothing(
    neo4j_driver: AsyncDriver,
) -> None:
    with pytest.raises(NotFound):
        await _run(
            neo4j_driver,
            lambda repo: repo.add(replace(UCR_WEST_V3, service_id="svc-none")),
        )
    assert await count_nodes(neo4j_driver, "Basic") == 0
    assert await count_nodes(neo4j_driver, "Resource") == 0


async def test_adding_an_existing_id_is_a_conflict(neo4j_driver: AsyncDriver) -> None:
    await _seed_service(neo4j_driver)
    await _run(neo4j_driver, lambda repo: repo.add(UCR_WEST_V3))
    with pytest.raises(Conflict):
        await _run(neo4j_driver, lambda repo: repo.add(UCR_WEST_V3))
    assert await count_nodes(neo4j_driver, "ServiceCriteria") == 1


async def test_adding_a_version_that_supersedes_an_unknown_version_is_not_found(
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed_service(neo4j_driver)
    with pytest.raises(NotFound):
        await _run(
            neo4j_driver,
            lambda repo: repo.add(replace(V4_PENDING, supersedes_id="crit-missing")),
        )
    assert await count_nodes(neo4j_driver, "ServiceCriteria") == 0


async def test_a_version_number_already_used_for_the_service_is_a_conflict(
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed_service(neo4j_driver)
    await _run(neo4j_driver, lambda repo: repo.add(V3_SUPERSEDED))
    copy = replace(V3_SUPERSEDED, id="crit-ucr-west-v3-copy", supersedes_id=None)
    with pytest.raises(Conflict):
        await _run(neo4j_driver, lambda repo: repo.add(copy))
    assert await count_nodes(neo4j_driver, "ServiceCriteria") == 1


async def test_saving_an_unknown_version_is_not_found(neo4j_driver: AsyncDriver) -> None:
    await _seed_service(neo4j_driver)
    with pytest.raises(NotFound):
        await _run(neo4j_driver, lambda repo: repo.save(V4_CURRENT))
    assert await count_nodes(neo4j_driver, "ServiceCriteria") == 0


@pytest.mark.parametrize(
    "changed",
    [
        pytest.param(replace(V3_SUPERSEDED, service_id="svc-other"), id="service"),
        pytest.param(replace(V3_SUPERSEDED, version=7), id="version-number"),
    ],
)
async def test_saving_cannot_move_a_version_to_another_service_or_number(
    neo4j_driver: AsyncDriver, changed: ServiceCriteria
) -> None:
    await _seed_service(neo4j_driver)
    await _run(neo4j_driver, lambda repo: repo.add(UCR_WEST_V3))
    with pytest.raises(ValidationFailed):
        await _run(neo4j_driver, lambda repo: repo.save(changed))
    assert await _read(neo4j_driver, lambda repo: repo.get(V3_ID)) == UCR_WEST_V3


async def test_two_racing_current_versions_leave_one_current(neo4j_driver: AsyncDriver) -> None:
    await _seed_service(neo4j_driver)
    await _run(
        neo4j_driver,
        lambda repo: repo.add(UCR_WEST_V3),
        lambda repo: repo.save(V3_SUPERSEDED),
    )
    rival = replace(V4_CURRENT, id="crit-ucr-west-v5", version=5, supersedes_id=V3_ID)
    session = neo4j_driver.session()
    held = await session.begin_transaction()
    try:
        await _repo(held).add(V4_CURRENT)
        racer = asyncio.create_task(write_tx(neo4j_driver, lambda tx: _repo(tx).add(rival)))
        done, _ = await asyncio.wait({racer}, timeout=1.0)
        assert not done, "the second writer must wait for the held write on the service"
    finally:
        await held.commit()
        await session.close()
    with pytest.raises(Conflict):
        await racer
    assert await count_nodes(neo4j_driver, "ServiceCriteria") == 2
    current = await _rows(
        neo4j_driver,
        "MATCH (:HealthcareService {id: $service})-[:CURRENT_CRITERIA]->(c) RETURN c.id AS id",
        service=SERVICE,
    )
    assert current == [{"id": V4_CURRENT.id}]


async def test_two_racing_writers_of_one_version_number_leave_one_version(
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed_service(neo4j_driver)
    await _run(neo4j_driver, lambda repo: repo.add(UCR_WEST_V3))
    twin = replace(V4_PENDING, id="crit-ucr-west-v4-twin")
    session = neo4j_driver.session()
    held = await session.begin_transaction()
    try:
        await _repo(held).add(V4_PENDING)
        racer = asyncio.create_task(write_tx(neo4j_driver, lambda tx: _repo(tx).add(twin)))
        done, _ = await asyncio.wait({racer}, timeout=1.0)
        assert not done, "the second writer must wait for the held write on the service"
    finally:
        await held.commit()
        await session.close()
    with pytest.raises(Conflict):
        await racer
    assert await count_nodes(neo4j_driver, "ServiceCriteria") == 2


async def test_two_racing_saves_that_make_a_version_current_leave_one_current(
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed_service(neo4j_driver)
    pending_v5 = replace(V4_PENDING, id="crit-ucr-west-v5", version=5)
    await _run(
        neo4j_driver,
        lambda repo: repo.add(UCR_WEST_V3),
        lambda repo: repo.add(V4_PENDING),
        lambda repo: repo.add(pending_v5),
        lambda repo: repo.save(V3_SUPERSEDED),
    )
    session = neo4j_driver.session()
    held = await session.begin_transaction()
    try:
        await _repo(held).save(V4_CURRENT)
        current_v5 = replace(pending_v5, status=CriteriaStatus.CURRENT)
        racer = asyncio.create_task(write_tx(neo4j_driver, lambda tx: _repo(tx).save(current_v5)))
        done, _ = await asyncio.wait({racer}, timeout=1.0)
        assert not done, "the second save must wait for the held write on the service"
    finally:
        await held.commit()
        await session.close()
    with pytest.raises(Conflict):
        await racer
    current = await _rows(
        neo4j_driver,
        "MATCH (:HealthcareService {id: $service})-[:CURRENT_CRITERIA]->(c) RETURN c.id AS id",
        service=SERVICE,
    )
    assert current == [{"id": V4_CURRENT.id}]
    assert await _read(neo4j_driver, lambda repo: repo.current_for_service(SERVICE)) == V4_CURRENT


async def test_a_service_with_a_current_version_still_reads_and_saves(
    neo4j_driver: AsyncDriver,
) -> None:
    # CURRENT_CRITERIA is a local relationship with no fhirPath. Before the loader skips it, the
    # service's own read fails with KeyError, which would break every service that has criteria.
    await _seed_service(neo4j_driver)
    await _run(neo4j_driver, lambda repo: repo.add(UCR_WEST_V3))

    async def read_service(tx: AsyncManagedTransaction) -> Any:
        return await Neo4jServiceRepository(tx, ResourceStore(tx)).get(SERVICE)

    assert await read_tx(neo4j_driver, read_service) == UCR_WEST

    async def save_service(tx: AsyncManagedTransaction) -> None:
        await Neo4jServiceRepository(tx, ResourceStore(tx)).save(UCR_WEST)

    await write_tx(neo4j_driver, save_service)
    # A service save clears the service's outgoing relationships (DEC-053 item 6), so the link
    # may be gone, but the current version is still found by its status.
    assert await _read(neo4j_driver, lambda repo: repo.current_for_service(SERVICE)) == UCR_WEST_V3
