"""The scope-list and invitation routes (R10) against real Neo4j through the API client.

WRITTEN, NOT RUN in this build (the wave 5 addendum: integration tests are run once, by the
orchestrator, on the merged tip). Each assertion reads back through a fresh session, not through
the route's answer alone.

The REST edge binds the lead's tenant from the signed token (TEN-018): every request sends a token
that names its tenant. The second tenant is seeded through its own unit of work and must not see
or change the first tenant's scope. Sample values only: no patient data, no real number.

Not covered here, and why: the registration's review and approval (the 409 listing of missing
checks, the happy path to `approved`) need a registration the reporter has submitted, which needs
the invited practitioner's own token. That flow is for the verification of the merged tip; the
rule's message is pinned by a unit test (test_routes_registration).
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
from diucs.application.ports.outbound.tokens import LINK_TOKEN_SECRET
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.bootstrap.container import Container, build_for_tests
from diucs.domain.codes import PractitionerRoleCode, Role, ScopeFlag, ServiceCategory
from diucs.domain.model.people import Practitioner, PractitionerRole
from diucs.domain.model.registration import ScopeEntry
from tests.support.api import R01_TEST_NOW, token_headers
from tests.support.neo4j import ThrowawayNeo4j
from tests.support.uow import ensure_audit_heads

pytestmark = pytest.mark.asyncio(loop_scope="session")

SCOPE_LIST = "/fhir/List/scope-list"
SCOPE_ENTRY = "/fhir/List/scope-list/$entry"
INVITE = "/fhir/Task/$invite-reporter"
MOBILE = "07700 900123"
PHONE_SECRET = b"phone-hash-test-secret-0123456789ab"
LINK_SECRET = b"link-token-test-secret-0123456789abcdef"
LEAD_SUB = "prac-lead"


@pytest_asyncio.fixture(loop_scope="session")
async def test_container(
    harness_container: ThrowawayNeo4j, neo4j_driver: AsyncDriver, clean_graph: None
) -> AsyncIterator[Container]:
    """The route container, with the two secrets the invitation hashes and links with. clean_graph
    runs here, before the edge seeds the tenants (lesson L84): a fixture after it would wipe
    them."""
    connection = Neo4jConnection(
        harness_container.uri, harness_container.user, harness_container.password
    )
    await connection.open()
    try:
        yield build_for_tests(
            clock=FixedClock(R01_TEST_NOW),
            neo4j=connection,
            secrets=FixedSecretStore(
                {PHONE_HASH_SECRET: PHONE_SECRET, LINK_TOKEN_SECRET: LINK_SECRET}
            ),
        )
    finally:
        await connection.close()


def _p(name: str, value: dict) -> dict:
    return {"name": name, **value}


def _entry(name: str = "UCR West", flag: str = "in-pilot", reason: str | None = None) -> dict:
    parts = [
        _p("service", {"valueString": name}),
        _p("category", {"valueCode": "urgent-community-response"}),
        _p("flag", {"valueCode": flag}),
    ]
    if reason is not None:
        parts.append(_p("reason", {"valueString": reason}))
    return {"resourceType": "Parameters", "parameter": parts}


def _invite(service_id: str, mobile: str = MOBILE) -> dict:
    return {
        "resourceType": "Parameters",
        "parameter": [
            _p("service", {"valueString": service_id}),
            _p("role", {"valueString": "Duty manager"}),
            _p("mobile", {"valueString": mobile}),
            _p("suggestedChannel", {"valueCode": "text"}),
        ],
    }


def _lead() -> dict[str, str]:
    return token_headers(role=Role.LEAD, sub=LEAD_SUB)


@pytest_asyncio.fixture(loop_scope="session")
async def scope_world(
    api_app: FastAPI,
    test_container: Container,
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    tenant_id: str,
) -> None:
    """A shift lead who holds the shift-lead post in the run tenant (the invitation checks it), and
    one scope entry in the second tenant that the run tenant must never see. The BFF secret and the
    replay cache are set as the other route tests set them (lesson L131)."""
    api_app.state.secrets = FixedSecretStore({BFF_SECRET_NAME: TEST_BFF_SECRET})
    api_app.state.cache = InMemoryCache(test_container.clock)
    await ensure_audit_heads(neo4j_driver, tenant_id)
    async with uow_factory_a() as uow:
        await uow.people.save_practitioner(
            Practitioner(id=LEAD_SUB, active=True, display_name="Shift lead", phone_hash=None)
        )
        await uow.people.save_role(
            PractitionerRole(
                id="role-lead",
                practitioner_id=LEAD_SUB,
                service_id=None,
                code=PractitionerRoleCode.SHIFT_LEAD,
                active=True,
                channel=None,
                period_start=R01_TEST_NOW,
            )
        )
        await uow.commit()
    async with uow_factory_b() as uow:
        await uow.scope.save_entry(
            ScopeEntry(
                service_id="svc-other-tenant",
                name="Other tenant service",
                # Another code from tenant A's: the shared schema keeps one Concept per code until
                # TEN-032 (lesson L169).
                category=ServiceCategory.REABLEMENT,
                flag=ScopeFlag.IN_PILOT,
                date=date(2026, 10, 23),
                reason="",
            )
        )
        await uow.commit()


async def test_a_lead_adds_a_scope_entry_and_the_list_and_the_stored_entry_show_its_flag(
    api_client: AsyncClient, scope_world: None, tenant_id: str, neo4j_driver: AsyncDriver
) -> None:
    added = await api_client.post(
        SCOPE_ENTRY,
        json=_entry(),
        headers={"Idempotency-Key": "scope-add-0001", **_lead()},
    )
    assert added.status_code == 201, added.text
    service_id = added.json()["parameter"][0]["valueString"]

    listing = await api_client.get(SCOPE_LIST, headers=_lead())

    assert listing.status_code == 200, listing.text
    rows = listing.json()["entry"]
    assert [row["item"]["reference"] for row in rows] == [f"HealthcareService/{service_id}"]
    assert rows[0]["flag"]["coding"][0]["code"] == "in-pilot"
    async with neo4j_driver.session() as session:
        result = await session.run(
            "MATCH (:List {id: 'scope-list', tenantId: $tenant})-[entry:ENTRY]->"
            "(:HealthcareService {id: $service, tenantId: $tenant}) RETURN entry.flag AS flag",
            tenant=tenant_id,
            service=service_id,
        )
        flags = [record["flag"] async for record in result]
    assert flags == ["in-pilot"]


async def test_an_advisor_cannot_add_a_scope_entry_and_nothing_is_stored(
    api_client: AsyncClient, scope_world: None, tenant_id: str, neo4j_driver: AsyncDriver
) -> None:
    refused = await api_client.post(
        SCOPE_ENTRY,
        json=_entry(name="Advisor attempt"),
        headers={
            "Idempotency-Key": "scope-add-0002",
            **token_headers(tenant_id, Role.ADVISOR),
        },
    )

    assert refused.status_code == 404
    async with neo4j_driver.session() as session:
        result = await session.run(
            "MATCH (:List {id: 'scope-list', tenantId: $tenant})-[:ENTRY]->({tenantId: $tenant}) "
            "RETURN count(*) AS entries",
            tenant=tenant_id,
        )
        entries = (await result.single())["entries"]
    assert entries == 0


async def test_a_service_flagged_later_cannot_be_invited_and_no_task_is_made(
    api_client: AsyncClient, scope_world: None, tenant_id: str, neo4j_driver: AsyncDriver
) -> None:
    added = await api_client.post(
        SCOPE_ENTRY,
        json=_entry(name="UCR Later", flag="later", reason="Not before the second wave"),
        headers={"Idempotency-Key": "scope-add-0003", **_lead()},
    )
    assert added.status_code == 201, added.text
    service_id = added.json()["parameter"][0]["valueString"]

    refused = await api_client.post(
        INVITE,
        json=_invite(service_id),
        headers={"Idempotency-Key": "invite-0001", **_lead()},
    )

    assert refused.status_code == 409, refused.text
    assert refused.json()["issue"][0]["code"] == "business-rule"
    async with neo4j_driver.session() as session:
        result = await session.run(
            "MATCH (t:Task {tenantId: $tenant}) RETURN count(t) AS tasks", tenant=tenant_id
        )
        tasks = (await result.single())["tasks"]
    assert tasks == 0


async def test_an_in_pilot_invitation_answers_with_the_last_four_digits_only(
    api_client: AsyncClient, scope_world: None
) -> None:
    added = await api_client.post(
        SCOPE_ENTRY,
        json=_entry(name="UCR Pilot"),
        headers={"Idempotency-Key": "scope-add-0004", **_lead()},
    )
    service_id = added.json()["parameter"][0]["valueString"]

    invited = await api_client.post(
        INVITE,
        json=_invite(service_id),
        headers={"Idempotency-Key": "invite-0002", **_lead()},
    )

    assert invited.status_code == 201, invited.text
    parts = {part["name"]: part for part in invited.json()["parameter"]}
    assert parts["numberEnding"]["valueString"] == "0123"
    assert "7700900123" not in invited.text
    assert "900123" not in invited.text


async def test_tenant_b_lead_sees_only_tenant_bs_scope_entries(
    api_client: AsyncClient, scope_world: None, other_tenant_id: str
) -> None:
    listing = await api_client.get(SCOPE_LIST, headers=token_headers(other_tenant_id, Role.LEAD))

    assert listing.status_code == 200, listing.text
    references = [row["item"]["reference"] for row in listing.json()["entry"]]
    assert references == ["HealthcareService/svc-other-tenant"]


async def test_tenant_b_cannot_invite_a_service_of_tenant_a_and_nothing_is_written(
    api_client: AsyncClient,
    scope_world: None,
    tenant_id: str,
    other_tenant_id: str,
    neo4j_driver: AsyncDriver,
) -> None:
    added = await api_client.post(
        SCOPE_ENTRY,
        json=_entry(name="UCR Shared Name"),
        headers={"Idempotency-Key": "scope-add-0005", **_lead()},
    )
    service_id = added.json()["parameter"][0]["valueString"]

    refused = await api_client.post(
        INVITE,
        json=_invite(service_id),
        headers={
            "Idempotency-Key": "invite-0003",
            **token_headers(other_tenant_id, Role.LEAD, sub=LEAD_SUB),
        },
    )

    assert refused.status_code == 404, refused.text
    async with neo4j_driver.session() as session:
        result = await session.run(
            "MATCH (t:Task {tenantId: $other}) RETURN count(t) AS tasks", other=other_tenant_id
        )
        tasks = (await result.single())["tasks"]
    assert tasks == 0


async def test_a_second_scope_entry_with_the_same_name_is_a_conflict(
    api_client: AsyncClient, scope_world: None
) -> None:
    first = await api_client.post(
        SCOPE_ENTRY,
        json=_entry(name="UCR Twice"),
        headers={"Idempotency-Key": "scope-add-0006", **_lead()},
    )
    again = await api_client.post(
        SCOPE_ENTRY,
        json=_entry(name="  ucr   twice "),
        headers={"Idempotency-Key": "scope-add-0007", **_lead()},
    )

    assert first.status_code == 201, first.text
    assert again.status_code == 409, again.text
    assert again.json()["issue"][0]["code"] == "conflict"
