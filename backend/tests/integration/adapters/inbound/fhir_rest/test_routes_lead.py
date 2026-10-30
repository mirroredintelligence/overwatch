"""The shift lead routes (R08) against real Neo4j through the API client.

The REST edge binds the lead's tenant from the signed token (TEN-018). Every request here sends a
token that names its tenant (tests/support/api.py token_headers), so the tenant is never ambient.
Each tenant has its own service and reporter role, written through that tenant's own unit of work,
so a change aimed at the other tenant's role must read as not found.

The phone numbers are the prompt's sample values. No patient data.
"""

from collections.abc import AsyncIterator
from dataclasses import replace

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient
from neo4j import AsyncDriver

from diucs.adapters.inbound.fhir_rest.auth import BFF_SECRET_NAME
from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.adapters.testing.tokens import TEST_BFF_SECRET
from diucs.application.ports.outbound.identity import PHONE_HASH_SECRET
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.bootstrap.container import Container, build_for_tests
from diucs.domain.codes import Channel, Measure, PractitionerRoleCode, Role, ServiceCategory
from diucs.domain.model.people import Practitioner, PractitionerRole
from diucs.domain.model.service import ServiceProfile
from tests.support.api import R01_TEST_NOW, token_headers
from tests.support.ladder_rig import reporter, seed_people, virtual_ward
from tests.support.neo4j import ThrowawayNeo4j, count_nodes
from tests.support.uow import ensure_audit_heads

pytestmark = pytest.mark.asyncio(loop_scope="session")

SETUP = "/fhir/HealthcareService/$setup"
CHANGE = "/fhir/PractitionerRole/{role}/$change-number"
NUMBER = "07700 900123"
NEW_NUMBER = "07700 900456"
SERVICE_A = "vw-frailty"
SERVICE_B = "vw-frailty-b"
ROLE_A = "role-1"
ROLE_B = "b-role-1"


def _p(name: str, value: dict) -> dict:
    return {"name": name, **value}


def _setup(mobile: str = NUMBER, channel: str = "text") -> dict:
    return {
        "resourceType": "Parameters",
        "parameter": [
            _p("name", {"valueString": "UCR West"}),
            _p("category", {"valueCode": "urgent-community-response"}),
            _p("measure", {"valueCode": "referrals-acceptable"}),
            _p("unitLabel", {"valueString": "referrals in the next 2 hrs"}),
            _p("establishedCapacity", {"valueInteger": 8}),
            _p("usualMin", {"valueInteger": 0}),
            _p("usualMax", {"valueInteger": 8}),
            _p("cadence", {"valueCode": "every-2-hrs"}),
            _p("channel", {"valueCode": channel}),
            _p("mobile", {"valueString": mobile}),
            _p("roleName", {"valueString": "Duty manager"}),
            _p("availableFrom", {"valueString": "08:00"}),
            _p("availableTo", {"valueString": "20:00"}),
            _p("ageMin", {"valueInteger": 18}),
            _p("district", {"valueString": "DT4"}),
            _p("accepts", {"valueCode": "frailty"}),
            _p("reviewBy", {"valueDate": "2026-12-12"}),
        ],
    }


def _change(mobile: str = NEW_NUMBER, duration: str = "today") -> dict:
    return {
        "resourceType": "Parameters",
        "parameter": [
            _p("mobile", {"valueString": mobile}),
            _p("duration", {"valueCode": duration}),
        ],
    }


PHONE_SECRET = b"phone-hash-test-secret-0123456789ab"


@pytest_asyncio.fixture(loop_scope="session")
async def test_container(
    harness_container: ThrowawayNeo4j, neo4j_driver: AsyncDriver, clean_graph: None
) -> AsyncIterator[Container]:
    """The route tests' container (tests/support/api.py), with the phone-hash secret the lead routes
    hash a mobile with. The shared one holds no secrets, and a missing secret is a NotFound, which
    answers 404 (the lead routes read the container's secrets, not the app's)."""
    connection = Neo4jConnection(
        harness_container.uri, harness_container.user, harness_container.password
    )
    await connection.open()
    try:
        yield build_for_tests(
            clock=FixedClock(R01_TEST_NOW),
            neo4j=connection,
            secrets=FixedSecretStore({PHONE_HASH_SECRET: PHONE_SECRET}),
        )
    finally:
        await connection.close()


async def _seed_tenant(
    factory: UnitOfWorkFactory,
    service: ServiceProfile,
    person: tuple[Practitioner, PractitionerRole],
) -> None:
    async with factory() as uow:
        await uow.services.save(service)
        await uow.commit()
    await seed_people(factory, person)


def _other_code(
    person: tuple[Practitioner, PractitionerRole],
) -> tuple[Practitioner, PractitionerRole]:
    """Tenant B's reporter role uses another practitioner-role code and another channel: the shared
    schema keeps one Concept per code (lesson L169), and tenant A's role already holds duty-manager
    and text."""
    practitioner, role = person
    return practitioner, replace(role, code=PractitionerRoleCode.COORDINATOR, channel=Channel.EMAIL)


@pytest_asyncio.fixture(loop_scope="session")
async def lead_world(
    api_app: FastAPI,
    test_container: Container,
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    tenant_id: str,
) -> None:
    """One service and one reporter role in each tenant, written through that tenant's own unit
    of work. The ids differ between the tenants because the shared harness schema keeps
    single-property keys until TEN-032, so tenant B uses other codes (lesson L169). Only the run
    tenant gets an audit head: a setup writes an
    audit entry there, and the other tenant's seed writes none. Two heads on the shared schema
    collide on the old single-property AuditHead key (lesson L157). It depends on api_app, which
    depends on edge_tenants and the container, so clean_graph has already wiped the graph (L84).
    The BFF secret store is set here, as the other route tests do (lesson L131)."""
    api_app.state.secrets = FixedSecretStore({BFF_SECRET_NAME: TEST_BFF_SECRET})
    # The writes are replayed through the cache (fail closed without one, lesson L131).
    api_app.state.cache = InMemoryCache(test_container.clock)
    await ensure_audit_heads(neo4j_driver, tenant_id)
    await _seed_tenant(uow_factory_a, virtual_ward(SERVICE_A), reporter(1, None))
    await _seed_tenant(
        uow_factory_b,
        virtual_ward(SERVICE_B, category=ServiceCategory.REABLEMENT, measure=Measure.FREE_BEDS),
        _other_code(reporter(1, None, SERVICE_B, prefix="b-")),
    )


async def test_a_lead_sets_up_a_service_and_a_fresh_read_finds_it(
    api_client: AsyncClient, lead_world: None, tenant_id: str, uow_factory_a: UnitOfWorkFactory
) -> None:
    # Precondition: the lead and the reporter role the routes read are visible in the run tenant
    # from the test's own unit of work, before the request is sent.
    async with uow_factory_a() as uow:
        assert await uow.people.get_practitioner("prac-1") is not None, "lead not seeded"
        assert await uow.people.get_role(ROLE_A) is not None, "reporter role not seeded"
    response = await api_client.post(
        SETUP,
        json=_setup(),
        headers={"Idempotency-Key": "setup-0001", **token_headers(tenant_id, Role.LEAD)},
    )

    assert response.status_code == 201, response.text
    assert response.json()["resourceType"] == "HealthcareService"
    assert response.json()["name"] == "UCR West"


async def test_the_mobile_is_kept_in_the_protected_store_only(
    api_client: AsyncClient, neo4j_driver: AsyncDriver, lead_world: None, tenant_id: str
) -> None:
    """The number is held by the ProtectedContact node and by no other node (DEC-070 item 2). The
    stored form is +44 and the subscriber digits, so the scan looks for those digits.
    That node holds it as plain text by recorded design; encryption at rest is not built (DEC-072
    item 4, pending information governance)."""
    await api_client.post(
        SETUP,
        json=_setup(),
        headers={"Idempotency-Key": "setup-0002", **token_headers(tenant_id, Role.LEAD)},
    )
    async with neo4j_driver.session() as session:
        result = await session.run(
            "MATCH (n {tenantId: $tenant}) WHERE any(k IN keys(n) WHERE valueType(n[k]) STARTS "
            "WITH 'STRING' "
            "AND n[k] CONTAINS '7700900123') "
            "RETURN labels(n) AS labels"
        )
        holders = [record["labels"] async for record in result]
    assert holders, "the number is stored somewhere"
    for labels in holders:
        assert labels == ["ProtectedContact"], labels


async def test_an_advisor_is_not_found_and_nothing_is_stored(
    api_client: AsyncClient, neo4j_driver: AsyncDriver, lead_world: None, tenant_id: str
) -> None:
    before = await count_nodes(neo4j_driver, "HealthcareService")
    response = await api_client.post(
        SETUP,
        json=_setup(),
        headers={"Idempotency-Key": "setup-0003", **token_headers(tenant_id, Role.ADVISOR)},
    )
    assert response.status_code == 404
    assert await count_nodes(neo4j_driver, "HealthcareService") == before


async def test_push_is_refused_outside_the_pilot(
    api_client: AsyncClient, lead_world: None, tenant_id: str
) -> None:
    response = await api_client.post(
        SETUP,
        json=_setup(channel="push"),
        headers={"Idempotency-Key": "setup-0004", **token_headers(tenant_id, Role.LEAD)},
    )
    assert response.status_code == 400


async def test_an_invalid_mobile_is_refused_and_the_input_is_not_echoed(
    api_client: AsyncClient, lead_world: None, tenant_id: str
) -> None:
    response = await api_client.post(
        SETUP,
        json=_setup(mobile="0770"),
        headers={"Idempotency-Key": "setup-0005", **token_headers(tenant_id, Role.LEAD)},
    )
    assert response.status_code == 400
    # The refusal text is the prompt's example number, "07700 900123", which contains the
    # characters "0770". So the check is on the input as a quoted value: the refusal must not
    # repeat the number that was sent.
    assert '"0770"' not in response.text


async def test_a_number_change_for_today_reports_the_last_four_digits(
    api_client: AsyncClient, lead_world: None, tenant_id: str
) -> None:
    response = await api_client.post(
        CHANGE.format(role=ROLE_A),
        json=_change(),
        headers={"Idempotency-Key": "change-0001", **token_headers(tenant_id, Role.LEAD)},
    )
    assert response.status_code == 200, response.text
    values = {p["name"]: p.get("valueString") for p in response.json()["parameter"]}
    assert values["numberEnding"] == "0456"


async def test_a_change_without_an_idempotency_key_is_refused(
    api_client: AsyncClient, lead_world: None, tenant_id: str
) -> None:
    response = await api_client.post(
        CHANGE.format(role=ROLE_A),
        json=_change(),
        headers=token_headers(tenant_id, Role.LEAD),
    )
    assert response.status_code == 400


async def test_another_tenants_reporter_role_reads_as_not_found(
    api_client: AsyncClient, lead_world: None, tenant_id: str
) -> None:
    """The lead of the run tenant names the other tenant's real role. It must read as not found,
    so the other tenant's role is never reached."""
    response = await api_client.post(
        CHANGE.format(role=ROLE_B),
        json=_change(),
        headers={"Idempotency-Key": "change-0002", **token_headers(tenant_id, Role.LEAD)},
    )
    assert response.status_code == 404
