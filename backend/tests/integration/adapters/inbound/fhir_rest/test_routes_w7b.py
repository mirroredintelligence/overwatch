"""The W7B reads and actions against real Neo4j through the API client, and what a second tenant
cannot see of them (W7B A1, A3, A4, B, C; DEC-130 to DEC-132).

Tenant A invites a reporter, the reporter drafts the registration (a part-filled step and a
24-hour location), the lead reads the invitations, the criteria owner reads the criteria with the
date of the change, and a suspension keeps the number of requests it expired. Tenant B, with the
same service and registration ids in its own graph where it has them, reads none of A's and gets
the 404 of a record that is not there. Each assertion reads through a fresh request or session.

Sample values only: no patient data, no real number.
"""

from collections.abc import AsyncIterator
from datetime import date, time

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
from diucs.domain.codes import (
    Cadence,
    Channel,
    CriteriaStatus,
    Measure,
    NeedCategory,
    PractitionerRoleCode,
    Role,
    ServiceCategory,
)
from diucs.domain.model.criteria import ServiceCriteria
from diucs.domain.model.flags import SERVICE_FLAG_SUSPENDED, ServiceFlag
from diucs.domain.model.people import Practitioner, PractitionerRole
from diucs.domain.model.service import AvailableTime, ServiceProfile
from tests.support.api import R01_TEST_NOW, token_headers
from tests.support.neo4j import ThrowawayNeo4j
from tests.support.uow import ensure_audit_heads

pytestmark = pytest.mark.asyncio(loop_scope="session")

PHONE_SECRET = b"phone-hash-test-secret-0123456789ab"
LINK_SECRET = b"link-token-test-secret-0123456789abcdef"
LEAD_SUB = "prac-lead"
OWNER_SUB = "prac-owner"
MOBILE = "07700 900123"
KEY = {"Content-Type": "application/json"}


@pytest_asyncio.fixture(loop_scope="session")
async def test_container(
    harness_container: ThrowawayNeo4j, neo4j_driver: AsyncDriver, clean_graph: None
) -> AsyncIterator[Container]:
    """The route container with the secrets the invitation hashes and links with. clean_graph runs
    here, before the edge seeds the tenants (lesson L84)."""
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


def _profile(service_id: str, name: str) -> ServiceProfile:
    return ServiceProfile(
        id=service_id,
        name=name,
        category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
        measure=Measure.REFERRALS_ACCEPTABLE,
        unit_label="referrals",
        established_capacity=8,
        can_exceed_established=False,
        usual_range=(0, 8),
        cadence=Cadence.EVERY_2_HRS,
        available_times=(AvailableTime.every_day(time(8, 0), time(20, 0)),),
        channel=Channel.TEXT,
    )


@pytest_asyncio.fixture(loop_scope="session")
async def world(
    api_app: FastAPI,
    test_container: Container,
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    """Tenant A: a lead, a service with a criteria owner and a current version, a suspended
    service. Tenant B: its own lead, so the second tenant's token can be used on A's ids."""
    api_app.state.secrets = FixedSecretStore({BFF_SECRET_NAME: TEST_BFF_SECRET})
    api_app.state.cache = InMemoryCache(test_container.clock)
    await ensure_audit_heads(neo4j_driver, tenant_id)
    async with uow_factory_a() as uow:
        await uow.services.save(_profile("ucr-west", "UCR West"))
        for person, label, role_id, code, service in (
            (LEAD_SUB, "Shift lead", "role-lead", PractitionerRoleCode.SHIFT_LEAD, None),
            (
                OWNER_SUB,
                "Clinical lead, UCR",
                "role-owner",
                PractitionerRoleCode.CRITERIA_OWNER,
                "ucr-west",
            ),
        ):
            await uow.people.save_practitioner(
                Practitioner(id=person, active=True, display_name=label, phone_hash=None)
            )
            await uow.people.save_role(
                PractitionerRole(
                    id=role_id,
                    practitioner_id=person,
                    service_id=service,
                    code=code,
                    active=True,
                    channel=None,
                    period_start=R01_TEST_NOW,
                )
            )
        await uow.criteria.add(
            ServiceCriteria(
                id="crit-1",
                service_id="ucr-west",
                version=1,
                status=CriteriaStatus.CURRENT,
                age_min=18,
                age_max=None,
                districts=frozenset({"DT4"}),
                accepts=frozenset({NeedCategory.FRAILTY}),
                excludes=frozenset(),
                review_by=date(2027, 1, 15),
                owner_role_id="role-owner",
                changed_on=date(2026, 9, 12),
            )
        )
        await uow.flags.set_service_flag(
            ServiceFlag(
                "ucr-west",
                SERVICE_FLAG_SUSPENDED,
                True,
                "closed-unexpectedly",
                LEAD_SUB,
                R01_TEST_NOW,
                expired_count=2,
            )
        )
        await uow.commit()
    await ensure_audit_heads(neo4j_driver, other_tenant_id)


async def test_the_owner_reads_the_criteria_with_the_date_of_the_change(
    api_client: AsyncClient, world: None
) -> None:
    response = await api_client.get(
        "/criteria/ucr-west", headers=token_headers(role=Role.OWNER, sub=OWNER_SUB)
    )

    assert response.status_code == 200, response.text
    current = response.json()["current"]
    assert (current["changedOn"], current["authorRole"]) == ("2026-09-12", "Clinical lead, UCR")
    history = await api_client.get(
        "/fhir/Basic?subject=HealthcareService/ucr-west",
        headers=token_headers(role=Role.OWNER, sub=OWNER_SUB),
    )
    entry = history.json()["entry"][0]["resource"]
    assert (entry["changedOn"], entry["authorRole"]) == ("2026-09-12", "Clinical lead, UCR")


async def test_the_lead_reads_the_suspension_and_the_number_of_requests_it_expired(
    api_client: AsyncClient, world: None
) -> None:
    response = await api_client.get(
        "/lead/services/ucr-west/suspension", headers=token_headers(role=Role.LEAD, sub=LEAD_SUB)
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["suspended"], body["reason"], body["expiredRequests"]) == (
        True,
        "closed-unexpectedly",
        2,
    )
    assert body["since"] == "2026-10-23T13:12:00Z"


async def test_the_lead_reads_the_reporters_overview_phones_and_invitations_of_the_tenant(
    api_client: AsyncClient, world: None
) -> None:
    headers = token_headers(role=Role.LEAD, sub=LEAD_SUB)
    for path, key in (
        ("/lead/overview", "chasing"),
        ("/lead/reporters", "reporters"),
        ("/lead/phones", "phones"),
        ("/lead/invitations", "items"),
    ):
        response = await api_client.get(path, headers=headers)
        assert response.status_code == 200, (path, response.text)
        assert key in response.json()


async def test_tenant_b_reads_none_of_tenant_as_criteria_suspension_or_service(
    api_client: AsyncClient, world: None, other_tenant_id: str
) -> None:
    other_lead = token_headers(other_tenant_id, Role.LEAD, sub=LEAD_SUB)
    other_owner = token_headers(other_tenant_id, Role.OWNER, sub=OWNER_SUB)
    other_clinical = token_headers(other_tenant_id, Role.CLINICAL, sub="prac-clinical")

    suspension = await api_client.get("/lead/services/ucr-west/suspension", headers=other_lead)
    reporters = await api_client.get("/lead/reporters?service=ucr-west", headers=other_lead)
    criteria = await api_client.get("/criteria/ucr-west", headers=other_clinical)
    owner = await api_client.get("/criteria/ucr-west", headers=other_owner)

    assert {suspension.status_code, reporters.status_code, criteria.status_code} == {404}
    assert owner.status_code == 404
    overview = (await api_client.get("/lead/overview", headers=other_lead)).json()
    assert overview["chasing"] == [] and overview["gettingOld"] == []
    assert overview["counts"] == {
        "accepting": 0,
        "limited": 0,
        "notAccepting": 0,
        "overCapacity": 0,
        "notUpdated": 0,
    }
    assert (await api_client.get("/lead/invitations", headers=other_lead)).json() == {"items": []}
    assert (await api_client.get("/lead/phones", headers=other_lead)).json() == {"phones": []}


async def test_a_registration_of_tenant_a_is_not_found_by_tenant_b(
    api_client: AsyncClient, world: None, other_tenant_id: str
) -> None:
    other_lead = token_headers(other_tenant_id, Role.LEAD, sub=LEAD_SUB)
    other_applicant = token_headers(other_tenant_id, Role.REPORTER, sub="prac-invitee")

    queue = await api_client.get("/registrations", headers=other_lead)
    overview = await api_client.get("/registrations/reg-1/overview", headers=other_lead)
    record = await api_client.get("/registrations/reg-1/record", headers=other_applicant)

    assert queue.status_code == 200 and queue.json()["registrations"] == []
    assert overview.status_code == record.status_code == 404


def _parts(**values: dict[str, str]) -> dict[str, object]:
    return {
        "resourceType": "Parameters",
        "parameter": [{"name": name, **value} for name, value in values.items()],
    }


async def test_an_invited_reporter_saves_a_part_filled_step_and_a_24_hour_location(
    api_client: AsyncClient, world: None, uow_factory_a: UnitOfWorkFactory
) -> None:
    lead = token_headers(role=Role.LEAD, sub=LEAD_SUB)
    added = await api_client.post(
        "/fhir/List/scope-list/$entry",
        json=_parts(
            service={"valueString": "UCR Pilot"},
            category={"valueCode": "urgent-community-response"},
            flag={"valueCode": "in-pilot"},
        ),
        headers={**KEY, "Idempotency-Key": "w7b-scope-0001", **lead},
    )
    assert added.status_code == 201, added.text
    service_id = added.json()["parameter"][0]["valueString"]
    invited = await api_client.post(
        "/fhir/Task/$invite-reporter",
        json=_parts(
            service={"valueString": service_id},
            role={"valueString": "Duty manager"},
            mobile={"valueString": MOBILE},
            suggestedChannel={"valueCode": "text"},
        ),
        headers={**KEY, "Idempotency-Key": "w7b-invite-0001", **lead},
    )
    assert invited.status_code == 201, invited.text
    parts = {part["name"]: part for part in invited.json()["parameter"]}
    registration_id = parts["registrationId"]["valueString"]
    async with uow_factory_a() as uow:
        invitation = await uow.registrations.get_invitation(parts["invitationId"]["valueString"])
    assert invitation is not None
    applicant = token_headers(role=Role.REPORTER, sub=invitation.invitee_id)

    started = await api_client.get(f"/registrations/{registration_id}/record", headers=applicant)
    assert started.status_code == 200, started.text
    assert started.json()["steps"]["organisation"]["state"] == "not-started"

    draft = await api_client.put(
        f"/fhir/Task/{registration_id}/$draft",
        json={"step": "organisation", "partial": True, "values": {"name": "Sample Team"}},
        headers={**KEY, "Idempotency-Key": "w7b-draft-0001", **applicant},
    )
    assert draft.status_code == 200, draft.text
    assert {item["field"] for item in draft.json()["incomplete"]} >= {"odsCode", "orgType"}

    location = await api_client.put(
        f"/fhir/Task/{registration_id}/$draft",
        json={
            "step": "location",
            "values": {
                "fixedSite": True,
                "postcode": "DT4 8XX",
                "address": "1 Sample Road, Weymouth",
                "siteName": "Sample Ward",
                "siteType": "ward",
                "open24h": True,
            },
        },
        headers={**KEY, "Idempotency-Key": "w7b-draft-0002", **applicant},
    )
    assert location.status_code == 200, location.text

    record = (
        await api_client.get(f"/registrations/{registration_id}/record", headers=applicant)
    ).json()
    assert record["status"] == "draft"
    assert record["steps"]["organisation"]["state"] == "needs-attention"
    assert record["steps"]["organisation"]["values"]["name"] == "Sample Team"
    assert record["steps"]["location"]["state"] == "complete"
    assert record["steps"]["location"]["values"]["open24h"] is True

    mine = await api_client.get("/my/registrations", headers=applicant)
    assert [row["registrationId"] for row in mine.json()["registrations"]] == [registration_id]
    items = (await api_client.get("/lead/invitations", headers=lead)).json()["items"]
    assert [item["id"] for item in items] == [parts["invitationId"]["valueString"]]
    assert items[0]["steps"]["channelChosen"] is False
    assert (
        MOBILE.replace(" ", "")[-8:]
        not in (await api_client.get(RECORD_PATH(registration_id), headers=applicant)).text
    )


def RECORD_PATH(registration_id: str) -> str:
    return f"/registrations/{registration_id}/record"
