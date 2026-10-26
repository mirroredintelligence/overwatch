"""Integration tests for the registration repository (P13).

They run against the throwaway Neo4j that the F10 harness starts for the pytest session (DEC-008).
Each write is one committed transaction and each read is a fresh session, so the tests assert on
what was really stored. The race tests hold one transaction open and start a second writer while
it is held (lesson L94). Values are synthetic; there is no patient data.
"""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.adapters.outbound.graph_store.registration_repository import Neo4jRegistrationRepository
from diucs.adapters.outbound.graph_store.service_repository import codeable_to_fhir
from diucs.domain.codes import CriteriaStatus, RegistrationStatus, ServiceCategory
from diucs.domain.errors import Conflict, NotFound, ValidationFailed
from diucs.domain.model.registration import Registration
from diucs.domain.rules.registration import ApprovalChecks
from tests.support.neo4j import count_nodes, node_props, read_tx, write_tx
from tests.support.round_trip import assert_round_trip

pytestmark = pytest.mark.asyncio(loop_scope="session")

EAST = "svc-ucr-east"
CREATED = datetime(2026, 10, 25, 12, 40, tzinfo=UTC)
DRAFT_FIELDS = {"organisation": {"name": "Dorset HealthCare", "ods": "RDY"}}

SUBMITTED_EAST = Registration(
    id="reg-ucr-east-1",
    service_id=EAST,
    status=RegistrationStatus.SUBMITTED,
    requester_role_id="role-applicant-1",
    owner_role_id=None,
    created_at=CREATED,
    last_modified=datetime(2026, 10, 25, 13, 5, tzinfo=UTC),
    submitted_at=datetime(2026, 10, 25, 13, 5, tzinfo=UTC),
    draft=DRAFT_FIELDS,
    checks=ApprovalChecks(True, False, None, False),
)


def _repo(tx: AsyncManagedTransaction) -> Neo4jRegistrationRepository:
    return Neo4jRegistrationRepository(tx, ResourceStore(tx))


async def _seed_service(driver: AsyncDriver, service_id: str) -> None:
    """A minimal service, written through the store as the scope list writes it."""

    async def work(tx: AsyncManagedTransaction) -> None:
        resource = {
            "resourceType": "HealthcareService",
            "id": service_id,
            "active": False,
            "name": "UCR East",
            "category": codeable_to_fhir(ServiceCategory.URGENT_COMMUNITY_RESPONSE),
        }
        await ResourceStore(tx).put(resource, None)

    await write_tx(driver, work)


async def _run(driver: AsyncDriver, *steps: Any) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        repo = _repo(tx)
        for step in steps:
            await step(repo)

    await write_tx(driver, work)


async def _read(driver: AsyncDriver, step: Any) -> Any:
    return await read_tx(driver, lambda tx: step(_repo(tx)))


async def _rows(driver: AsyncDriver, cypher: str, **params: Any) -> list[dict[str, Any]]:
    async def work(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        result = await tx.run(cypher, **params)
        return await result.data()

    return await read_tx(driver, work)


async def test_a_submitted_registration_for_ucr_east_round_trips(
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed_service(neo4j_driver, EAST)

    async def save(tx: AsyncManagedTransaction) -> None:
        await _repo(tx).add(SUBMITTED_EAST)

    async def load(tx: AsyncManagedTransaction) -> Registration | None:
        return await _repo(tx).get("reg-ucr-east-1")

    await assert_round_trip(neo4j_driver, save, load, SUBMITTED_EAST)


async def test_submitted_registrations_are_listed_in_submission_order_and_drafts_are_not(
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed_service(neo4j_driver, EAST)
    at_1305 = SUBMITTED_EAST
    at_1330 = replace(
        SUBMITTED_EAST,
        id="reg-ucr-east-2",
        submitted_at=datetime(2026, 10, 25, 13, 30, tzinfo=UTC),
    )
    at_1250 = replace(
        SUBMITTED_EAST,
        id="reg-ucr-east-3",
        submitted_at=datetime(2026, 10, 25, 12, 50, tzinfo=UTC),
    )
    draft = replace(
        SUBMITTED_EAST,
        id="reg-ucr-east-4",
        status=RegistrationStatus.DRAFT,
        submitted_at=None,
    )
    await _run(
        neo4j_driver,
        lambda repo: repo.add(at_1305),
        lambda repo: repo.add(at_1330),
        lambda repo: repo.add(at_1250),
        lambda repo: repo.add(draft),
    )

    listed = await _read(
        neo4j_driver, lambda repo: repo.list_by_status(RegistrationStatus.SUBMITTED)
    )

    assert [r.id for r in listed] == ["reg-ucr-east-3", "reg-ucr-east-1", "reg-ucr-east-2"]


async def test_listing_by_a_criteria_status_with_the_same_value_is_refused(
    neo4j_driver: AsyncDriver,
) -> None:
    # Lesson L38: CriteriaStatus.DRAFT and RegistrationStatus.DRAFT both hold "draft" and compare
    # equal, so a status lookup must check the enum type before it matches the business status.
    assert CriteriaStatus.DRAFT == RegistrationStatus.DRAFT
    await _seed_service(neo4j_driver, EAST)
    draft = replace(SUBMITTED_EAST, id="reg-ucr-east-5", status=RegistrationStatus.DRAFT)
    await _run(neo4j_driver, lambda repo: repo.add(draft))

    with pytest.raises(ValidationFailed):
        await _read(neo4j_driver, lambda repo: repo.list_by_status(CriteriaStatus.DRAFT))


async def test_saving_submitted_as_in_review_updates_the_business_status(
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed_service(neo4j_driver, EAST)
    await _run(neo4j_driver, lambda repo: repo.add(SUBMITTED_EAST))
    in_review = replace(SUBMITTED_EAST, status=RegistrationStatus.IN_REVIEW)

    await _run(neo4j_driver, lambda repo: repo.save(in_review))

    props = await node_props(neo4j_driver, "Task", id="reg-ucr-east-1")
    assert props["businessStatus"] == "in-review"
    assert await _read(neo4j_driver, lambda repo: repo.get("reg-ucr-east-1")) == in_review


async def test_a_save_replaces_the_draft_as_a_whole(neo4j_driver: AsyncDriver) -> None:
    await _seed_service(neo4j_driver, EAST)
    await _run(neo4j_driver, lambda repo: repo.add(SUBMITTED_EAST))
    replaced = replace(
        SUBMITTED_EAST,
        draft={"reporting": {"phone_checked": True}},
    )

    await _run(neo4j_driver, lambda repo: repo.save(replaced))

    loaded = await _read(neo4j_driver, lambda repo: repo.get("reg-ucr-east-1"))
    assert loaded is not None
    assert loaded.draft == {"reporting": {"phone_checked": True}}
    assert await count_nodes(neo4j_driver, "RegistrationDraftField") == 1


async def test_a_registration_task_is_coded_register_service(neo4j_driver: AsyncDriver) -> None:
    await _seed_service(neo4j_driver, EAST)
    await _run(neo4j_driver, lambda repo: repo.add(SUBMITTED_EAST))

    rows = await _rows(
        neo4j_driver,
        "MATCH (:Task {id: $id})-[:CODE]->(c:Concept) RETURN c.code AS code",
        id="reg-ucr-east-1",
    )

    assert rows == [{"code": "register-service"}]


async def test_the_stored_nodes_hold_no_map_no_json_and_no_list_of_maps(
    neo4j_driver: AsyncDriver,
) -> None:
    # DEC-001: a schema test over the registration's own nodes.
    await _seed_service(neo4j_driver, EAST)
    await _run(neo4j_driver, lambda repo: repo.add(SUBMITTED_EAST))

    async def nodes(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        result = await tx.run(
            "MATCH (n) WHERE n:Task OR n:RegistrationDraftField RETURN properties(n) AS props"
        )
        return [dict(row["props"]) for row in await result.data()]

    stored = await read_tx(neo4j_driver, nodes)

    assert stored
    for props in stored:
        for name, value in props.items():
            assert not isinstance(value, dict), name
            if isinstance(value, list):
                assert not any(isinstance(item, dict) for item in value), name
            if isinstance(value, str):
                assert not value.lstrip().startswith(("{", "[")), name


async def test_for_service_lists_the_newest_registration_first(
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed_service(neo4j_driver, EAST)
    older = replace(SUBMITTED_EAST, id="reg-ucr-east-old", created_at=CREATED)
    newer = replace(
        SUBMITTED_EAST,
        id="reg-ucr-east-new",
        created_at=datetime(2026, 10, 25, 14, 0, tzinfo=UTC),
    )
    await _run(neo4j_driver, lambda repo: repo.add(older), lambda repo: repo.add(newer))

    found = await _read(neo4j_driver, lambda repo: repo.for_service(EAST))

    assert [r.id for r in found] == ["reg-ucr-east-new", "reg-ucr-east-old"]


async def test_adding_for_an_unknown_service_is_not_found_and_writes_nothing(
    neo4j_driver: AsyncDriver,
) -> None:
    with pytest.raises(NotFound):
        await _run(neo4j_driver, lambda repo: repo.add(SUBMITTED_EAST))

    assert await count_nodes(neo4j_driver, "Task") == 0


async def test_adding_an_existing_registration_is_a_conflict(neo4j_driver: AsyncDriver) -> None:
    await _seed_service(neo4j_driver, EAST)
    await _run(neo4j_driver, lambda repo: repo.add(SUBMITTED_EAST))

    with pytest.raises(Conflict):
        await _run(neo4j_driver, lambda repo: repo.add(SUBMITTED_EAST))


async def test_saving_an_unknown_registration_is_not_found(neo4j_driver: AsyncDriver) -> None:
    await _seed_service(neo4j_driver, EAST)

    with pytest.raises(NotFound):
        await _run(neo4j_driver, lambda repo: repo.save(SUBMITTED_EAST))

    assert await count_nodes(neo4j_driver, "Task") == 0


async def test_a_save_waits_for_a_held_save_and_a_refused_save_leaves_its_draft(
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed_service(neo4j_driver, EAST)
    await _run(neo4j_driver, lambda repo: repo.add(SUBMITTED_EAST))
    held_draft = {"organisation": {"name": "Dorset HealthCare", "ods": "RDY"}, "n": {"v": 2}}
    racing_draft = {"reporting": {"phone_checked": False}}
    session = neo4j_driver.session()
    held = await session.begin_transaction()
    try:
        await _repo(held).save(replace(SUBMITTED_EAST, draft=held_draft))
        racer = asyncio.create_task(
            write_tx(
                neo4j_driver,
                lambda tx: _repo(tx).save(replace(SUBMITTED_EAST, draft=racing_draft)),
            )
        )
        done, _ = await asyncio.wait({racer}, timeout=1.0)
        assert not done, "the second save must wait for the held write on the registration"
    finally:
        await held.commit()
        await session.close()
    with pytest.raises(Conflict):
        await racer
    loaded = await _read(neo4j_driver, lambda repo: repo.get("reg-ucr-east-1"))
    assert loaded is not None
    assert loaded.draft == held_draft
    assert await count_nodes(neo4j_driver, "RegistrationDraftField") == 3
