"""The criteria routes (R10) against real Neo4j through the API client.

WRITTEN, NOT RUN in this build (the wave 5 addendum: integration tests are run once, by the
orchestrator, on the merged tip). Each assertion reads back through a fresh session.

The run tenant holds one service with a current criteria version, written by its criteria owner.
The owner submits a change (a version waiting for approval). The owner cannot approve it (a 404);
a clinical lead approves it, and the history then reads newest first with the old version
superseded. The second tenant sees no history for the same service id. Sample values only.
"""

from collections.abc import AsyncIterator
from datetime import date

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
from diucs.domain.codes import CriteriaStatus, NeedCategory, PractitionerRoleCode, Role
from diucs.domain.model.criteria import ServiceCriteria
from diucs.domain.model.people import Practitioner, PractitionerRole
from tests.support.api import R01_TEST_NOW, token_headers
from tests.support.ladder_rig import virtual_ward
from tests.support.neo4j import ThrowawayNeo4j
from tests.support.uow import ensure_audit_heads

EMPTY_PARAMETERS = {"resourceType": "Parameters"}

pytestmark = pytest.mark.asyncio(loop_scope="session")

SERVICE = "svc-criteria"
CURRENT = "crit-v1"
OWNER = "prac-owner"
LEAD = "prac-clinical-lead"


def _p(name: str, value: dict) -> dict:
    return {"name": name, **value}


def _change(months: int = 6) -> dict:
    return {
        "resourceType": "Parameters",
        "parameter": [
            _p("service", {"valueString": SERVICE}),
            _p("ageMin", {"valueInteger": 16}),
            _p("accepts", {"valueCode": "frailty"}),
            _p("district", {"valueString": "DT4"}),
            _p("changeReason", {"valueString": "Age range widened"}),
            _p("reviewMonths", {"valueInteger": months}),
        ],
    }


@pytest_asyncio.fixture(loop_scope="session")
async def test_container(
    harness_container: ThrowawayNeo4j, neo4j_driver: AsyncDriver, clean_graph: None
) -> AsyncIterator[Container]:
    """The route container with the phone-hash secret. clean_graph runs here, before the edge seeds
    the tenants (lesson L84)."""
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
async def criteria_world(
    api_app: FastAPI,
    test_container: Container,
    uow_factory_a: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    tenant_id: str,
) -> None:
    """A service, its current criteria and its owner in the run tenant, and a clinical lead who may
    approve for every service. The BFF secret and the replay cache are set as the other route tests
    set them (lesson L131)."""
    api_app.state.secrets = FixedSecretStore({BFF_SECRET_NAME: TEST_BFF_SECRET})
    api_app.state.cache = InMemoryCache(test_container.clock)
    await ensure_audit_heads(neo4j_driver, tenant_id)
    async with uow_factory_a() as uow:
        await uow.services.save(virtual_ward(SERVICE))
        await uow.people.save_practitioner(
            Practitioner(id=OWNER, active=True, display_name="Criteria owner", phone_hash=None)
        )
        await uow.people.save_role(
            PractitionerRole(
                id="role-owner",
                practitioner_id=OWNER,
                service_id=SERVICE,
                code=PractitionerRoleCode.CRITERIA_OWNER,
                active=True,
                channel=None,
                period_start=R01_TEST_NOW,
            )
        )
        await uow.people.save_practitioner(
            Practitioner(id=LEAD, active=True, display_name="Clinical lead", phone_hash=None)
        )
        await uow.people.save_role(
            PractitionerRole(
                id="role-clinical-lead",
                practitioner_id=LEAD,
                service_id=None,
                code=PractitionerRoleCode.CLINICAL_LEAD,
                active=True,
                channel=None,
                period_start=R01_TEST_NOW,
            )
        )
        await uow.criteria.add(
            ServiceCriteria(
                id=CURRENT,
                service_id=SERVICE,
                version=1,
                status=CriteriaStatus.CURRENT,
                age_min=18,
                age_max=None,
                districts=frozenset({"DT4"}),
                accepts=frozenset({NeedCategory.FRAILTY}),
                excludes=frozenset(),
                review_by=date(2026, 12, 12),
                owner_role_id="role-owner",
            )
        )
        await uow.commit()


async def test_the_owner_submits_a_change_and_it_waits_for_approval(
    api_client: AsyncClient, criteria_world: None, tenant_id: str
) -> None:
    response = await api_client.post(
        "/fhir/Basic",
        json=_change(),
        headers={
            "Idempotency-Key": "criteria-change-0001",
            **token_headers(tenant_id, Role.OWNER, sub=OWNER),
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["status"] == "pending-approval"
    assert response.json()["meta"]["versionId"] == "2"


async def test_the_owner_cannot_approve_their_own_change(
    api_client: AsyncClient, criteria_world: None, tenant_id: str
) -> None:
    submitted = await api_client.post(
        "/fhir/Basic",
        json=_change(),
        headers={
            "Idempotency-Key": "criteria-change-0002",
            **token_headers(tenant_id, Role.OWNER, sub=OWNER),
        },
    )
    criteria_id = submitted.json()["id"]

    refused = await api_client.post(
        f"/fhir/Basic/{criteria_id}/$approve", json=EMPTY_PARAMETERS,
        headers={
            "Idempotency-Key": "criteria-approve-0001",
            **token_headers(tenant_id, Role.OWNER, sub=OWNER),
        },
    )

    assert refused.status_code == 404, refused.text


async def test_a_clinical_lead_approves_the_change_and_history_reads_newest_first(
    api_client: AsyncClient, criteria_world: None, tenant_id: str
) -> None:
    submitted = await api_client.post(
        "/fhir/Basic",
        json=_change(),
        headers={
            "Idempotency-Key": "criteria-change-0003",
            **token_headers(tenant_id, Role.OWNER, sub=OWNER),
        },
    )
    criteria_id = submitted.json()["id"]

    approved = await api_client.post(
        f"/fhir/Basic/{criteria_id}/$approve", json=EMPTY_PARAMETERS,
        headers={
            "Idempotency-Key": "criteria-approve-0002",
            **token_headers(tenant_id, Role.LEAD, sub=LEAD),
        },
    )
    history = await api_client.get(
        "/fhir/Basic",
        params={"subject": f"HealthcareService/{SERVICE}"},
        headers=token_headers(tenant_id, Role.OWNER, sub=OWNER),
    )

    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "current"
    versions = [entry["resource"] for entry in history.json()["entry"]]
    assert [version["meta"]["versionId"] for version in versions] == ["2", "1"]
    assert [version["status"] for version in versions] == ["current", "superseded"]


async def test_the_owner_confirms_a_review_period_of_six_months(
    api_client: AsyncClient, criteria_world: None, tenant_id: str
) -> None:
    response = await api_client.post(
        f"/fhir/HealthcareService/{SERVICE}/$confirm-criteria",
        json={
            "resourceType": "Parameters",
            "parameter": [_p("reviewInMonths", {"valueInteger": 6})],
        },
        headers={
            "Idempotency-Key": "criteria-confirm-0001",
            **token_headers(tenant_id, Role.OWNER, sub=OWNER),
        },
    )

    assert response.status_code == 200, response.text
    assert any(part["name"] == "reviewBy" for part in response.json()["parameter"])


async def test_tenant_b_sees_no_criteria_history_for_the_same_service_id(
    api_client: AsyncClient, criteria_world: None, other_tenant_id: str
) -> None:
    history = await api_client.get(
        "/fhir/Basic",
        params={"subject": f"HealthcareService/{SERVICE}"},
        headers=token_headers(other_tenant_id, Role.OWNER, sub=OWNER),
    )

    assert history.status_code == 200, history.text
    assert history.json()["total"] == 0
    assert history.json().get("entry", []) == []
