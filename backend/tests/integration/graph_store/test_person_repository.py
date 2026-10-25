"""Integration tests for the person repository (P03).

Run against the throwaway Neo4j that the F10 harness starts for the pytest session (DEC-008). Each
write is one committed transaction and each read is a fresh session, so the tests assert on what
was really stored. All values are synthetic: there is no patient data and no phone number, only the
keyed hash the tests supply.
"""

import asyncio
import dataclasses
from datetime import UTC, datetime
from typing import Any

import pytest
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.person_repository import Neo4jPersonRepository
from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.domain.codes import Channel, PractitionerRoleCode
from diucs.domain.errors import Conflict, NotFound
from diucs.domain.model.people import Practitioner, PractitionerRole, role_holder
from tests.support.neo4j import count_nodes, node_props, read_tx, write_tx
from tests.support.round_trip import assert_round_trip

pytestmark = pytest.mark.asyncio(loop_scope="session")

PERIOD_START = datetime(2026, 10, 1, tzinfo=UTC)
NOW = datetime(2026, 10, 25, 13, 0, tzinfo=UTC)
COVER_UNTIL = datetime(2026, 10, 25, 19, 0, tzinfo=UTC)
SERVICE_NAMES = {"svc-ucr-west": "UCR West", "svc-ucr-east": "UCR East"}

P1 = Practitioner(id="p1", active=True, display_name="Duty Manager One", phone_hash="h1")
P2 = Practitioner(id="p2", active=True, display_name="Cover Manager Two", phone_hash="h2")

ROLE_WEST = PractitionerRole(
    id="r-west",
    practitioner_id="p1",
    service_id="svc-ucr-west",
    code=PractitionerRoleCode.DUTY_MANAGER,
    active=True,
    channel=Channel.TEXT,
    period_start=PERIOD_START,
)
ROLE_EAST = PractitionerRole(
    id="r-east",
    practitioner_id="p1",
    service_id="svc-ucr-east",
    code=PractitionerRoleCode.DUTY_MANAGER,
    active=True,
    channel=Channel.TEXT,
    period_start=PERIOD_START,
)
ROLE_EAST_COVERED = dataclasses.replace(
    ROLE_EAST, covered_by_practitioner_id="p2", covered_until=COVER_UNTIL
)


def _repo(tx: AsyncManagedTransaction) -> Neo4jPersonRepository:
    return Neo4jPersonRepository(tx, ResourceStore(tx))


async def _seed_services(tx: AsyncManagedTransaction) -> None:
    store = ResourceStore(tx)
    for service_id, name in SERVICE_NAMES.items():
        resource: dict[str, Any] = {
            "resourceType": "HealthcareService",
            "id": service_id,
            "active": True,
            "name": name,
        }
        await store.put(resource, None)


async def _write(driver: AsyncDriver, *steps: Any) -> None:
    """Run each step in its own committed write. A step is (practitioner | role) or the string
    'services' for the two services."""

    async def work(tx: AsyncManagedTransaction) -> None:
        repo = _repo(tx)
        for step in steps:
            if step == "services":
                await _seed_services(tx)
            elif isinstance(step, Practitioner):
                await repo.save_practitioner(step)
            else:
                await repo.save_role(step)

    await write_tx(driver, work)


async def _count_rels(driver: AsyncDriver, rel_type: str) -> int:
    query = f"MATCH ()-[r:`{rel_type}`]->() RETURN count(r) AS total"

    async def work(tx: AsyncManagedTransaction) -> int:
        record = await (await tx.run(query)).single()
        assert record is not None
        return int(record["total"])

    return await read_tx(driver, work)


async def test_p1_round_trips_with_its_phone_hash_as_a_node_property(
    neo4j_driver: AsyncDriver,
) -> None:
    async def save(tx: AsyncManagedTransaction) -> None:
        await _repo(tx).save_practitioner(P1)

    async def load(tx: AsyncManagedTransaction) -> Practitioner | None:
        return await _repo(tx).get_practitioner("p1")

    await assert_round_trip(neo4j_driver, save, load, P1)

    props = await node_props(neo4j_driver, "Practitioner", id="p1")
    assert props["phoneHash"] == "h1"


async def test_the_duty_manager_role_round_trips_with_its_text_channel(
    neo4j_driver: AsyncDriver,
) -> None:
    async def save(tx: AsyncManagedTransaction) -> None:
        await _seed_services(tx)
        await _repo(tx).save_practitioner(P1)
        await _repo(tx).save_role(ROLE_WEST)

    async def load(tx: AsyncManagedTransaction) -> list[PractitionerRole]:
        return await _repo(tx).roles_for_practitioner("p1")

    await assert_round_trip(neo4j_driver, save, load, [ROLE_WEST])
    assert await _count_rels(neo4j_driver, "CHANNEL") == 1


async def test_phone_h1_gets_both_services_it_holds_sorted_by_service_id(
    neo4j_driver: AsyncDriver,
) -> None:
    await _write(neo4j_driver, "services", P1, ROLE_WEST, ROLE_EAST)

    services = await read_tx(neo4j_driver, lambda tx: _repo(tx).services_for_phone_hash("h1", NOW))

    assert services == [(ROLE_EAST, "UCR East"), (ROLE_WEST, "UCR West")]


async def test_a_cover_moves_east_to_phone_h2_until_19_00_and_then_reverts(
    neo4j_driver: AsyncDriver,
) -> None:
    await _write(neo4j_driver, "services", P1, P2, ROLE_WEST, ROLE_EAST_COVERED)

    h1_now = await read_tx(neo4j_driver, lambda tx: _repo(tx).services_for_phone_hash("h1", NOW))
    h2_now = await read_tx(neo4j_driver, lambda tx: _repo(tx).services_for_phone_hash("h2", NOW))
    h1_after = await read_tx(
        neo4j_driver, lambda tx: _repo(tx).services_for_phone_hash("h1", COVER_UNTIL)
    )
    h2_after = await read_tx(
        neo4j_driver, lambda tx: _repo(tx).services_for_phone_hash("h2", COVER_UNTIL)
    )

    assert h1_now == [(ROLE_WEST, "UCR West")]
    assert h2_now == [(ROLE_EAST_COVERED, "UCR East")]
    assert h1_after == [(ROLE_EAST_COVERED, "UCR East"), (ROLE_WEST, "UCR West")]
    assert h2_after == []
    assert role_holder(ROLE_EAST_COVERED, NOW) == "p2"
    assert role_holder(ROLE_EAST_COVERED, COVER_UNTIL) == "p1"


async def test_the_cover_is_a_covered_by_relationship_with_its_until(
    neo4j_driver: AsyncDriver,
) -> None:
    await _write(neo4j_driver, "services", P1, P2, ROLE_EAST_COVERED)

    async def until(tx: AsyncManagedTransaction) -> list[datetime]:
        result = await tx.run("MATCH ()-[c:COVERED_BY]->(:Practitioner) RETURN c.until AS until")
        return [record["until"].to_native() for record in await result.data()]

    assert await read_tx(neo4j_driver, until) == [COVER_UNTIL]


async def test_an_inactive_practitioner_is_not_found_by_phone(neo4j_driver: AsyncDriver) -> None:
    inactive = dataclasses.replace(P1, active=False)
    await _write(neo4j_driver, inactive)

    found = await read_tx(neo4j_driver, lambda tx: _repo(tx).find_by_phone_hash("h1"))

    assert found is None


async def test_an_active_practitioner_is_found_by_phone_hash(neo4j_driver: AsyncDriver) -> None:
    await _write(neo4j_driver, P1)

    assert await read_tx(neo4j_driver, lambda tx: _repo(tx).find_by_phone_hash("h1")) == P1
    assert await read_tx(neo4j_driver, lambda tx: _repo(tx).find_by_phone_hash("nope")) is None


async def test_an_inactive_role_is_excluded_from_phone_and_person_lookups(
    neo4j_driver: AsyncDriver,
) -> None:
    inactive = dataclasses.replace(ROLE_WEST, active=False)
    await _write(neo4j_driver, "services", P1, inactive)

    services = await read_tx(neo4j_driver, lambda tx: _repo(tx).services_for_phone_hash("h1", NOW))
    roles = await read_tx(neo4j_driver, lambda tx: _repo(tx).roles_for_practitioner("p1"))

    assert services == []
    assert roles == []


async def test_a_criteria_owner_role_is_not_a_reporter_role(neo4j_driver: AsyncDriver) -> None:
    owner = dataclasses.replace(ROLE_WEST, code=PractitionerRoleCode.CRITERIA_OWNER)
    await _write(neo4j_driver, "services", P1, owner)

    services = await read_tx(neo4j_driver, lambda tx: _repo(tx).services_for_phone_hash("h1", NOW))
    reporters = await read_tx(
        neo4j_driver, lambda tx: _repo(tx).reporter_roles_for_service("svc-ucr-west", NOW)
    )
    roles = await read_tx(neo4j_driver, lambda tx: _repo(tx).roles_for_practitioner("p1"))

    assert services == []
    assert reporters == []
    assert roles == [owner]


async def test_a_coordinator_role_is_a_reporter_role(neo4j_driver: AsyncDriver) -> None:
    coordinator = dataclasses.replace(ROLE_EAST, code=PractitionerRoleCode.COORDINATOR)
    await _write(neo4j_driver, "services", P1, coordinator)

    reporters = await read_tx(
        neo4j_driver, lambda tx: _repo(tx).reporter_roles_for_service("svc-ucr-east", NOW)
    )

    assert reporters == [coordinator]


async def test_reporter_roles_for_a_service_keep_the_cover_for_the_caller_to_resolve(
    neo4j_driver: AsyncDriver,
) -> None:
    await _write(neo4j_driver, "services", P1, P2, ROLE_EAST_COVERED)

    reporters = await read_tx(
        neo4j_driver, lambda tx: _repo(tx).reporter_roles_for_service("svc-ucr-east", NOW)
    )

    assert reporters == [ROLE_EAST_COVERED]
    assert role_holder(reporters[0], NOW) == "p2"


async def test_saving_a_role_without_its_cover_removes_the_covered_by_relationship(
    neo4j_driver: AsyncDriver,
) -> None:
    await _write(neo4j_driver, "services", P1, P2, ROLE_EAST_COVERED)
    assert await _count_rels(neo4j_driver, "COVERED_BY") == 1

    await _write(neo4j_driver, ROLE_EAST)

    assert await _count_rels(neo4j_driver, "COVERED_BY") == 0
    services = await read_tx(neo4j_driver, lambda tx: _repo(tx).services_for_phone_hash("h2", NOW))
    assert services == []


async def _refused_then_committed(driver: AsyncDriver, *steps: Any) -> None:
    """Run each step, then a role save that is expected to raise NotFound. The caller catches the
    refusal and the transaction commits anyway, so a write made before the refusal would persist
    (lesson L68). Earlier steps are committed in their own writes first."""
    await _write(driver, *steps[:-1])

    async def refused_save(tx: AsyncManagedTransaction) -> None:
        with pytest.raises(NotFound):
            await _repo(tx).save_role(steps[-1])

    await write_tx(driver, refused_save)


async def test_a_role_for_an_unknown_practitioner_is_refused_and_writes_nothing(
    neo4j_driver: AsyncDriver,
) -> None:
    await _refused_then_committed(neo4j_driver, "services", ROLE_WEST)

    assert await count_nodes(neo4j_driver, "PractitionerRole") == 0
    assert await count_nodes(neo4j_driver, "Practitioner") == 0


async def test_a_role_for_an_unknown_service_is_refused_and_writes_nothing(
    neo4j_driver: AsyncDriver,
) -> None:
    await _refused_then_committed(neo4j_driver, P1, ROLE_WEST)

    assert await count_nodes(neo4j_driver, "PractitionerRole") == 0
    assert await count_nodes(neo4j_driver, "HealthcareService") == 0


async def test_a_cover_by_an_unknown_practitioner_is_refused_and_writes_nothing(
    neo4j_driver: AsyncDriver,
) -> None:
    await _refused_then_committed(neo4j_driver, "services", P1, ROLE_EAST_COVERED)

    assert await count_nodes(neo4j_driver, "PractitionerRole") == 0
    assert await count_nodes(neo4j_driver, "Practitioner") == 1
    assert await _count_rels(neo4j_driver, "COVERED_BY") == 0


async def test_sixteen_racing_saves_of_one_new_practitioner_let_exactly_one_win(
    neo4j_driver: AsyncDriver,
) -> None:
    async def save_once() -> str:
        try:
            await write_tx(neo4j_driver, lambda tx: _repo(tx).save_practitioner(P1))
        except Conflict:
            return "conflict"
        return "saved"

    outcomes = await asyncio.gather(*(save_once() for _ in range(16)))

    assert outcomes.count("saved") == 1
    assert outcomes.count("conflict") == 15
    assert await count_nodes(neo4j_driver, "Practitioner") == 1
