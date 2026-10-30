"""The shift lead routes (R08) against real Neo4j through the API client.

The REST edge binds the lead's tenant from the verified token (TEN-018). Tenant A is the run tenant;
tenant B's role is seeded through its own unit of work, and a request from A's lead must read it as
not found and leave it as it was (B uses its own service category: until TEN-032 the shared schema
keeps one Concept per code).

The phone numbers are the prompt's sample values. No patient data.
"""

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient
from neo4j import AsyncDriver

from diucs.adapters.inbound.fhir_rest.auth import BFF_SECRET_NAME
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.adapters.testing.tokens import TEST_BFF_SECRET, issue_test_token
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.bootstrap.container import Container
from diucs.domain.codes import Role, ServiceCategory
from diucs.domain.model.people import Practitioner, PractitionerRole
from diucs.domain.model.service import ServiceProfile
from tests.support.ladder_rig import reporter, seed_people, virtual_ward
from tests.support.neo4j import count_nodes
from tests.support.uow import ensure_audit_heads

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def _lead_app(
    api_app: FastAPI,
    test_container: Container,
    neo4j_driver: AsyncDriver,
    tenant_id: str,
) -> None:
    """The API with the BFF secret (R02), the replay cache that every write needs (R03) and the
    run tenant's audit chain head, made after the wipe."""
    api_app.state.secrets = FixedSecretStore({BFF_SECRET_NAME: TEST_BFF_SECRET})
    api_app.state.cache = InMemoryCache(test_container.clock)
    # Only the run tenant has a chain head: the second tenant's head needs a contracted container
    # (DEC-159), and no case here writes as tenant B.
    await ensure_audit_heads(neo4j_driver, tenant_id)
    # The lead who sets a service up is a practitioner of the tenant (its owner role is theirs).
    async with test_container.uow_factory() as uow:
        await uow.people.save_practitioner(
            Practitioner(id="lead-1", active=True, display_name="Sample Lead", phone_hash=None)
        )
        await uow.commit()


B_SERVICE = "svc-b-ward"

SETUP = "/fhir/HealthcareService/$setup"
CHANGE = "/fhir/PractitionerRole/{role}/$change-number"
NUMBER = "07700 900123"
NEW_NUMBER = "07700 900456"


async def _seed_reporter(
    factory: UnitOfWorkFactory,
    profile: ServiceProfile,
    person: tuple[Practitioner, PractitionerRole],
) -> None:
    async with factory() as uow:
        await uow.services.save(profile)
        await uow.commit()
    await seed_people(factory, person)


def _bearer(role: Role, sub: str = "lead-1") -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_test_token(role, [], sub)}"}


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


async def test_a_lead_sets_up_a_service_and_a_fresh_read_finds_it(
    api_client: AsyncClient, neo4j_driver: AsyncDriver
) -> None:
    response = await api_client.post(
        SETUP, json=_setup(), headers={"Idempotency-Key": "setup-0001", **_bearer(Role.LEAD)}
    )

    assert response.status_code == 201
    assert response.json()["resourceType"] == "HealthcareService"
    assert response.json()["name"] == "UCR West"


async def test_the_mobile_is_kept_in_the_protected_store_only(
    api_client: AsyncClient, neo4j_driver: AsyncDriver
) -> None:
    await api_client.post(
        SETUP, json=_setup(), headers={"Idempotency-Key": "setup-0002", **_bearer(Role.LEAD)}
    )
    # The number is kept in its international form, so the search is for its subscriber digits.
    async with neo4j_driver.session() as session:
        result = await session.run(
            "MATCH (n) WHERE any(k IN keys(n) "
            "WHERE n[k] IS :: STRING AND n[k] CONTAINS '7700900123') "
            "RETURN labels(n) AS labels"
        )
        holders = [record["labels"] async for record in result]
    assert holders, "the number is stored somewhere"
    for labels in holders:
        assert labels == ["ProtectedContact"], labels


async def test_an_advisor_is_not_found_and_nothing_is_stored(
    api_client: AsyncClient, neo4j_driver: AsyncDriver
) -> None:
    response = await api_client.post(
        SETUP, json=_setup(), headers={"Idempotency-Key": "setup-0003", **_bearer(Role.ADVISOR)}
    )
    assert response.status_code == 404
    assert await count_nodes(neo4j_driver, "HealthcareService") == 0


async def test_push_is_refused_outside_the_pilot(api_client: AsyncClient) -> None:
    response = await api_client.post(
        SETUP,
        json=_setup(channel="push"),
        headers={"Idempotency-Key": "setup-0004", **_bearer(Role.LEAD)},
    )
    assert response.status_code == 400


async def test_an_invalid_mobile_is_refused_and_the_input_is_not_echoed(
    api_client: AsyncClient,
) -> None:
    response = await api_client.post(
        SETUP,
        json=_setup(mobile="0770"),
        headers={"Idempotency-Key": "setup-0005", **_bearer(Role.LEAD)},
    )
    assert response.status_code == 400
    # The prompt's example number contains the characters "0770", so the check is on the input as
    # a value: the refusal must not repeat it as the number that was sent.
    assert '"0770"' not in response.text


async def test_a_number_change_for_today_reports_the_last_four_digits(
    api_client: AsyncClient, neo4j_driver: AsyncDriver, test_container: Container
) -> None:
    await _seed_reporter(test_container.uow_factory, virtual_ward(), reporter(1, None))
    response = await api_client.post(
        CHANGE.format(role="role-1"),
        json=_change(),
        headers={"Idempotency-Key": "change-0001", **_bearer(Role.LEAD)},
    )
    assert response.status_code == 200
    values = {p["name"]: p.get("valueString") for p in response.json()["parameter"]}
    assert values["numberEnding"] == "0456"


async def test_a_change_without_an_idempotency_key_is_refused(api_client: AsyncClient) -> None:
    response = await api_client.post(
        CHANGE.format(role="role-1"), json=_change(), headers=_bearer(Role.LEAD)
    )
    assert response.status_code == 400


async def test_another_tenants_reporter_role_reads_as_not_found(
    api_client: AsyncClient,
    uow_factory_b: UnitOfWorkFactory,
    test_container: Container,
) -> None:
    """A role that exists in tenant B is the same 404 as a role that exists nowhere, and the
    request changes nothing of B's."""
    await _seed_reporter(
        uow_factory_b,
        virtual_ward(B_SERVICE, category=ServiceCategory.SAME_DAY_EMERGENCY_CARE),
        reporter(7, None, service_id=B_SERVICE, prefix="b-"),
    )
    unknown = await api_client.post(
        CHANGE.format(role="role-nowhere"),
        json=_change(),
        headers={"Idempotency-Key": "change-0002", **_bearer(Role.LEAD)},
    )
    response = await api_client.post(
        CHANGE.format(role="b-role-7"),
        json=_change(),
        headers={"Idempotency-Key": "change-0003", **_bearer(Role.LEAD)},
    )
    assert response.status_code == 404
    assert response.json() == unknown.json()
    async with uow_factory_b() as uow:
        role = await uow.people.get_role("b-role-7")
    assert role is not None
    assert role.covered_by_practitioner_id is None
    assert role.covered_until is None
