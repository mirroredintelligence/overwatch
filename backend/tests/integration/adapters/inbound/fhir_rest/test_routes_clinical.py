"""The clinical presence, count, take and safety-concern routes (R13) against real Neo4j.

WRITTEN, NOT RUN in this build (the wave 5 addendum: integration tests are run once, by the
orchestrator, on the merged tip). Each assertion reads back through a fresh unit of work.

Not covered here: the advisor's request for advice and its advice, which need a closed case to
ask about, and the lock of a taken request (for the verification of the merged tip). Sample values
only; the safety text is a sample sentence.
"""

import re
from collections.abc import AsyncIterator

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
from diucs.application.ports.outbound.tokens import LINK_TOKEN_SECRET
from diucs.bootstrap.container import Container, build_for_tests
from diucs.domain.codes import PractitionerRoleCode, Role, code_system_url
from diucs.domain.model.people import Practitioner, PractitionerRole
from tests.support.api import R01_TEST_NOW, token_headers
from tests.support.neo4j import ThrowawayNeo4j
from tests.support.uow import ensure_audit_heads

EMPTY_PARAMETERS = {"resourceType": "Parameters"}

pytestmark = pytest.mark.asyncio(loop_scope="session")

PRESENCE = "/clinical/presence"
AVAILABLE = "/clinical/available"
TASK = "/fhir/Task"
SAFETY_TEXT = "The board showed the wrong service for the sample referral."
# The key that seals the clinical safety officer's notice (queue_message): a safety concern needs it.
LINK_SECRET = b"link-token-test-secret-0123456789abcdef"


@pytest_asyncio.fixture(loop_scope="session")
async def test_container(
    harness_container: ThrowawayNeo4j, neo4j_driver: AsyncDriver, clean_graph: None
) -> AsyncIterator[Container]:
    """The route container. clean_graph runs here, before the edge seeds the tenants (L84)."""
    connection = Neo4jConnection(
        harness_container.uri, harness_container.user, harness_container.password
    )
    await connection.open()
    try:
        yield build_for_tests(
            clock=FixedClock(R01_TEST_NOW),
            neo4j=connection,
            secrets=FixedSecretStore(
                {PHONE_HASH_SECRET: b"phone-hash-test-secret-0123456789ab", LINK_TOKEN_SECRET: LINK_SECRET}
            ),
        )
    finally:
        await connection.close()


@pytest_asyncio.fixture(loop_scope="session")
async def clinical_world(
    api_app: FastAPI,
    test_container: Container,
    neo4j_driver: AsyncDriver,
    tenant_id: str,
    uow_factory_a: UnitOfWorkFactory,
) -> None:
    """The replay cache and presence store are set as the other route tests set them (lesson L131).
    The run tenant's audit head exists before any write. The clinician who sets a presence is a
    clinical lead in the graph: the count only reads the clinical leads (AvailableClinicians)."""
    api_app.state.secrets = FixedSecretStore({BFF_SECRET_NAME: TEST_BFF_SECRET})
    api_app.state.cache = InMemoryCache(test_container.clock)
    await ensure_audit_heads(neo4j_driver, tenant_id)
    async with uow_factory_a() as uow:
        await uow.people.save_practitioner(
            Practitioner(id="clin-1", active=True, display_name="Clinician", phone_hash=None)
        )
        await uow.people.save_role(
            PractitionerRole(
                id="role-clin-1",
                practitioner_id="clin-1",
                service_id=None,
                code=PractitionerRoleCode.CLINICAL_LEAD,
                active=True,
                channel=None,
                period_start=R01_TEST_NOW,
            )
        )
        await uow.commit()


async def test_a_clinician_goes_available_and_the_count_names_no_one(
    api_client: AsyncClient, clinical_world: None, tenant_id: str
) -> None:
    set_busy = await api_client.put(
        PRESENCE,
        json={"presence": "available"},
        headers=token_headers(tenant_id, Role.CLINICAL, sub="clin-1"),
    )
    count = await api_client.get(AVAILABLE, headers=token_headers(tenant_id, Role.ADVISOR))

    assert set_busy.status_code == 200, set_busy.text
    assert count.status_code == 200, count.text
    assert isinstance(count.json()["available"], int)
    assert count.json()["available"] >= 1
    assert "clin-1" not in count.text


async def test_a_safety_concern_returns_a_reference_and_never_the_text(
    api_client: AsyncClient, clinical_world: None, tenant_id: str
) -> None:
    concern = {
        "resourceType": "Task",
        "code": {"coding": [{"code": "safety-concern"}]},
        "extension": [
            {
                "url": code_system_url("task-input/category"),
                "valueCode": "wrong-service-shown",
            },
            {"url": code_system_url("task-input/text"), "valueString": SAFETY_TEXT},
        ],
    }

    response = await api_client.post(
        TASK,
        json=concern,
        headers={
            "Idempotency-Key": "concern-0001",
            **token_headers(tenant_id, Role.EXEC, sub="exec-1"),
        },
    )

    assert response.status_code == 201, response.text
    reference = response.json()["identifier"][0]["value"]
    assert re.fullmatch(r"SC-\d{4}", reference)
    assert SAFETY_TEXT not in response.text


async def test_taking_a_request_that_does_not_exist_is_not_found(
    api_client: AsyncClient, clinical_world: None, tenant_id: str
) -> None:
    response = await api_client.post(
        "/fhir/Task/req-missing/$take", json=EMPTY_PARAMETERS,
        headers={
            "Idempotency-Key": "take-0001",
            **token_headers(tenant_id, Role.CLINICAL, sub="clin-1"),
        },
    )

    assert response.status_code == 404, response.text


async def test_a_lead_is_not_a_clinical_advisor_for_the_queue(
    api_client: AsyncClient, clinical_world: None, tenant_id: str
) -> None:
    response = await api_client.get(
        "/fhir/Task",
        params={"code": "clinical-advice", "status": "requested"},
        headers=token_headers(tenant_id, Role.LEAD, sub="prac-lead"),
    )

    assert response.status_code == 404, response.text
