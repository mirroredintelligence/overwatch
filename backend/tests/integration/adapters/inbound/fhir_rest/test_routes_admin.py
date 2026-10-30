"""The lead, flag and audit routes (R13) against real Neo4j through the API client.

WRITTEN, NOT RUN in this build (the wave 5 addendum: integration tests are run once, by the
orchestrator, on the merged tip). Each assertion reads back through a fresh unit of work.

Not covered here, and why: the lost-phone start and check (`/identity/new-phone`) and the
sign-out-everywhere route need the Redis session and code stores, and the clinical advice flow
needs a closed case; those are for the verification of the merged tip. Sample values only.
"""

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
from diucs.bootstrap.container import Container, build_for_tests
from diucs.domain.codes import Role
from tests.support.api import R01_TEST_NOW, token_headers
from tests.support.ladder_rig import virtual_ward
from tests.support.neo4j import ThrowawayNeo4j
from tests.support.uow import ensure_audit_heads

pytestmark = pytest.mark.asyncio(loop_scope="session")

SERVICE = "svc-admin"
LEAD = "prac-lead"
SUSPEND = f"/fhir/HealthcareService/{SERVICE}/$suspend"
RESUME = f"/fhir/HealthcareService/{SERVICE}/$resume"


def _parameters(*parts: tuple[str, dict]) -> dict:
    return {
        "resourceType": "Parameters",
        "parameter": [{"name": name, **value} for name, value in parts],
    }


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
            secrets=FixedSecretStore({PHONE_HASH_SECRET: b"phone-hash-test-secret-0123456789ab"}),
        )
    finally:
        await connection.close()


@pytest_asyncio.fixture(loop_scope="session")
async def admin_world(
    api_app: FastAPI,
    test_container: Container,
    uow_factory_a: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    tenant_id: str,
) -> None:
    """One service in the run tenant. The BFF secret and the replay cache are set as the other route
    tests set them (lesson L131)."""
    api_app.state.secrets = FixedSecretStore({BFF_SECRET_NAME: TEST_BFF_SECRET})
    api_app.state.cache = InMemoryCache(test_container.clock)
    await ensure_audit_heads(neo4j_driver, tenant_id)
    async with uow_factory_a() as uow:
        await uow.services.save(virtual_ward(SERVICE))
        await uow.commit()


async def test_a_lead_suspends_a_service_and_the_answer_says_whether_it_notified(
    api_client: AsyncClient, admin_world: None, tenant_id: str
) -> None:
    response = await api_client.post(
        SUSPEND,
        json=_parameters(("reason", {"valueCode": "other"})),
        headers={
            "Idempotency-Key": "suspend-0001",
            **token_headers(tenant_id, Role.LEAD, sub=LEAD),
        },
    )

    assert response.status_code == 200, response.text
    parts = {part["name"]: part for part in response.json()["parameter"]}
    assert parts["notified"]["valueBoolean"] is False  # no wording is set for the run tenant


async def test_an_advisor_cannot_suspend_and_the_service_is_untouched(
    api_client: AsyncClient, admin_world: None, tenant_id: str
) -> None:
    response = await api_client.post(
        SUSPEND,
        json=_parameters(("reason", {"valueCode": "other"})),
        headers={"Idempotency-Key": "suspend-0002", **token_headers(tenant_id, Role.ADVISOR)},
    )

    assert response.status_code == 404, response.text


async def test_a_resume_without_the_call_back_is_refused_before_anything_changes(
    api_client: AsyncClient, admin_world: None, tenant_id: str
) -> None:
    response = await api_client.post(
        RESUME,
        json=_parameters(
            ("calledBack", {"valueBoolean": False}),
            ("reasonResolved", {"valueBoolean": True}),
        ),
        headers={"Idempotency-Key": "resume-0001", **token_headers(tenant_id, Role.LEAD, sub=LEAD)},
    )

    assert response.status_code == 400, response.text
    assert response.json()["issue"][0]["expression"] == ["calledBack"]


async def test_tenant_b_cannot_suspend_tenant_as_service(
    api_client: AsyncClient, admin_world: None, other_tenant_id: str
) -> None:
    response = await api_client.post(
        SUSPEND,
        json=_parameters(("reason", {"valueCode": "other"})),
        headers={
            "Idempotency-Key": "suspend-0003",
            **token_headers(other_tenant_id, Role.LEAD, sub=LEAD),
        },
    )

    assert response.status_code == 404, response.text


async def test_the_open_flag_list_is_a_bundle_and_empty_for_a_new_tenant(
    api_client: AsyncClient, admin_world: None, tenant_id: str
) -> None:
    response = await api_client.get(
        "/admin/report-flags",
        params={"status": "open"},
        headers=token_headers(tenant_id, Role.LEAD, sub=LEAD),
    )

    assert response.status_code == 200, response.text
    assert response.json()["resourceType"] == "Bundle"
    assert response.json()["total"] == 0


async def test_an_audit_replay_of_an_unknown_case_is_not_found_for_the_auditor(
    api_client: AsyncClient, admin_world: None, tenant_id: str
) -> None:
    response = await api_client.get(
        "/admin/audit/SC-9999", headers=token_headers(tenant_id, Role.AUDIT)
    )

    assert response.status_code == 404, response.text


async def test_an_advisor_cannot_read_the_audit_replay(
    api_client: AsyncClient, admin_world: None, tenant_id: str
) -> None:
    response = await api_client.get(
        "/admin/audit/SC-9999", headers=token_headers(tenant_id, Role.ADVISOR)
    )

    assert response.status_code == 404, response.text
