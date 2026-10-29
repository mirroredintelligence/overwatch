"""Round 2 (verifier finding) integration tests for the person repository.

Each test runs against the throwaway Neo4j of the F10 harness (DEC-008). Values are synthetic.
"""

import dataclasses
from datetime import UTC, datetime
from typing import Any

import pytest
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.person_repository import Neo4jPersonRepository
from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.application.tenancy import current_tenant
from diucs.domain.codes import Channel, PractitionerRoleCode
from diucs.domain.errors import Conflict, ValidationFailed
from diucs.domain.model.people import Practitioner, PractitionerRole
from tests.support.neo4j import count_nodes, read_tx, write_tx

pytestmark = pytest.mark.asyncio(loop_scope="session")

H1 = "a" * 64
H_OTHER = "b" * 64
NOW = datetime(2026, 10, 25, 13, 0, tzinfo=UTC)
PERIOD_START = datetime(2026, 10, 1, tzinfo=UTC)
P1 = Practitioner(id="p1", active=True, display_name="Duty Manager One", phone_hash=H1)


def _repo(tx: AsyncManagedTransaction) -> Neo4jPersonRepository:
    return Neo4jPersonRepository(tx, ResourceStore(tx))


def _role(role_id: str, service_id: str) -> PractitionerRole:
    return PractitionerRole(
        id=role_id,
        practitioner_id="p1",
        service_id=service_id,
        code=PractitionerRoleCode.DUTY_MANAGER,
        active=True,
        channel=Channel.TEXT,
        period_start=PERIOD_START,
    )


async def _seed(driver: AsyncDriver, services: dict[str, str], *people: Practitioner) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        store = ResourceStore(tx)
        for service_id, name in services.items():
            resource: dict[str, Any] = {
                "resourceType": "HealthcareService",
                "id": service_id,
                "active": True,
                "name": name,
            }
            await store.put(resource, None)
        for person in people:
            await _repo(tx).save_practitioner(person)

    await write_tx(driver, work)


async def test_a_raw_phone_number_cannot_become_a_practitioner_and_writes_nothing(
    neo4j_driver: AsyncDriver,
) -> None:
    async def attempt(tx: AsyncManagedTransaction) -> None:
        with pytest.raises(ValidationFailed) as refused:
            person = Practitioner(
                id="p9", active=True, display_name="Duty", phone_hash="07700900123"
            )
            await _repo(tx).save_practitioner(person)
        assert refused.value.field == "phone_hash"
        assert "07700900123" not in str(refused.value)

    await write_tx(neo4j_driver, attempt)

    assert await count_nodes(neo4j_driver, "Resource") == 0
    assert await count_nodes(neo4j_driver, "Practitioner") == 0


async def test_a_raw_phone_number_is_refused_at_the_phone_lookups(
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed(neo4j_driver, {}, P1)

    with pytest.raises(ValidationFailed) as found:
        await read_tx(neo4j_driver, lambda tx: _repo(tx).find_by_phone_hash("07700900123"))
    with pytest.raises(ValidationFailed) as services:
        await read_tx(
            neo4j_driver,
            lambda tx: _repo(tx).services_for_phone_hash("07700900123", NOW),
        )

    assert found.value.field == "phone_hash"
    assert services.value.field == "phone_hash"
    assert "07700900123" not in str(found.value)


async def test_two_active_practitioners_sharing_a_phone_hash_make_the_lookup_conflict(
    neo4j_driver: AsyncDriver,
) -> None:
    twin = dataclasses.replace(P1, id="p2")
    await _seed(neo4j_driver, {}, P1, twin)

    with pytest.raises(Conflict):
        await read_tx(neo4j_driver, lambda tx: _repo(tx).find_by_phone_hash(H1))


async def test_one_active_practitioner_is_still_found_when_an_inactive_twin_exists(
    neo4j_driver: AsyncDriver,
) -> None:
    inactive_twin = dataclasses.replace(P1, id="p2", active=False)
    await _seed(neo4j_driver, {}, P1, inactive_twin)

    found = await read_tx(neo4j_driver, lambda tx: _repo(tx).find_by_phone_hash(H1))

    assert found == P1


async def test_services_for_a_phone_are_ordered_by_name_then_id(
    neo4j_driver: AsyncDriver,
) -> None:
    services = {"svc-z-first": "Alpha", "svc-a-second": "Alpha", "svc-m-third": "Beta"}
    await _seed(neo4j_driver, services, P1)

    async def save_roles(tx: AsyncManagedTransaction) -> None:
        for role_id, service_id in (
            ("r-z", "svc-z-first"),
            ("r-a", "svc-a-second"),
            ("r-m", "svc-m-third"),
        ):
            await _repo(tx).save_role(_role(role_id, service_id))

    await write_tx(neo4j_driver, save_roles)

    found = await read_tx(neo4j_driver, lambda tx: _repo(tx).services_for_phone_hash(H1, NOW))

    assert [(role.service_id, name) for role, name in found] == [
        ("svc-a-second", "Alpha"),
        ("svc-z-first", "Alpha"),
        ("svc-m-third", "Beta"),
    ]


async def test_a_relationship_without_a_fhir_path_that_is_not_local_still_fails_the_read(
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed(neo4j_driver, {"svc-ucr-west": "UCR West"}, P1)

    async def save_and_add_stray(tx: AsyncManagedTransaction) -> None:
        await _repo(tx).save_role(_role("r-west", "svc-ucr-west"))
        await tx.run(
            "MATCH (r:PractitionerRole {key: 'PractitionerRole/r-west', tenantId: $tenant}) "
            "CREATE (c:Concept {system: 'stray', code: 'x', key: 'Concept|stray|x', "
            "tenantId: $tenant}) "
            "CREATE (r)-[:STRAY]->(c)",
            tenant=current_tenant(),
        )

    await write_tx(neo4j_driver, save_and_add_stray)

    async def read(tx: AsyncManagedTransaction) -> Any:
        return await ResourceStore(tx).get("PractitionerRole", "r-west")

    with pytest.raises(KeyError):
        await read_tx(neo4j_driver, read)
