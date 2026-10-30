"""The advisor case routes (R07) against real Neo4j through the API client.

The edge binds the tenant from the signed token (TEN-018). Services, criteria and reports are seeded
through the tenant's own unit of work. Clock: 23 October 2026, 14:12 London. Synthetic values only;
the case holds the postcode district DT4 and no name, identifier, birth date or telecom.
"""

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient
from neo4j import AsyncDriver

from diucs.adapters.inbound.fhir_rest.auth import BFF_SECRET_NAME
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.adapters.testing.tokens import TEST_BFF_SECRET
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.domain.codes import (
    Cadence,
    Channel,
    CriteriaStatus,
    Measure,
    NeedCategory,
    ReportSource,
    ReportType,
    Role,
    ServiceCategory,
)
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.criteria import ServiceCriteria
from diucs.domain.model.service import AvailableTime, ServiceProfile
from tests.support.api import token_headers
from tests.support.neo4j import count_nodes, wipe
from tests.support.uow import ensure_audit_heads

pytestmark = pytest.mark.asyncio(loop_scope="session")

UCR_WEST = "svc-ucr-west"
WARD_B = "svc-ward-b"
CASE_BODY: dict[str, Any] = {
    "resourceType": "ServiceRequest",
    "status": "active",
    "intent": "plan",
    "priority": "urgent",
    "subject": {"reference": "#p"},
    "contained": [
        {
            "resourceType": "Patient",
            "id": "p",
            "address": [{"postalCode": "DT4"}],
            "extension": [
                {
                    "url": "https://diucs.example/StructureDefinition/age-band",
                    "valueCode": "80+",
                }
            ],
        }
    ],
    "reasonCode": [
        {
            "coding": [
                {
                    "system": "https://diucs.example/CodeSystem/need-category",
                    "code": "fall-no-injury",
                },
                {
                    "system": "https://diucs.example/CodeSystem/need-category",
                    "code": "frailty",
                },
            ]
        }
    ],
    "extension": [
        {
            "url": "https://diucs.example/StructureDefinition/referrer-type",
            "valueCode": "ambulance-crew",
        }
    ],
}
IDEMPOTENT = {"Idempotency-Key": "case-open-1"}


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
        available_times=(AvailableTime.every_day_all_day(),),
        channel=Channel.TEXT,
        limited_level_percent=80,
    )


def _criteria(service_id: str) -> ServiceCriteria:
    return ServiceCriteria(
        id=f"crit-{service_id}-v1",
        service_id=service_id,
        version=1,
        status=CriteriaStatus.CURRENT,
        age_min=18,
        age_max=None,
        districts=frozenset({"DT1", "DT2", "DT3", "DT4"}),
        accepts=frozenset({NeedCategory.FALL_NO_INJURY, NeedCategory.FRAILTY}),
        excludes=frozenset(),
        review_by=date(2026, 12, 31),
        owner_role_id="role-lead-west",
    )


def _report(service_id: str, value: int, at: datetime, number: int) -> CapacityReport:
    return CapacityReport(
        id=f"obs-{number}",
        service_id=service_id,
        value=value,
        measure=Measure.REFERRALS_ACCEPTABLE,
        effective_at=at,
        source=ReportSource.TEXT,
        report_type=ReportType.NUMBER,
    )


@pytest_asyncio.fixture(loop_scope="session")
async def seeded(neo4j_driver: AsyncDriver, uow_factory: UnitOfWorkFactory, tenant_id: str) -> None:
    """Two services with current criteria and a current report each (UCR West accepts, Ward B is
    not accepting)."""
    await ensure_audit_heads(neo4j_driver, tenant_id)
    async with uow_factory() as uow:
        for service_id, name in ((UCR_WEST, "UCR West"), (WARD_B, "Ward B")):
            await uow.services.save(_profile(service_id, name))
            await uow.criteria.add(_criteria(service_id))
        await uow.capacity.add(_report(UCR_WEST, 4, datetime(2026, 10, 23, 13, 4, tzinfo=UTC), 1))
        await uow.capacity.add(_report(WARD_B, 0, datetime(2026, 10, 23, 12, 58, tzinfo=UTC), 2))
        await uow.commit()


async def test_an_advisor_opens_a_case_with_a_district_and_no_name(
    api_client: AsyncClient, seeded: None, neo4j_driver: AsyncDriver
) -> None:
    response = await api_client.post(
        "/fhir/ServiceRequest",
        json=CASE_BODY,
        headers={**token_headers(role=Role.ADVISOR), **IDEMPOTENT},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["priority"] == "urgent"
    assert body["status"] == "active"
    assert body["intent"] == "plan"
    assert body["contained"][0]["address"][0]["postalCode"] == "DT4"
    assert "name" not in body["contained"][0]
    assert await count_nodes(neo4j_driver, "ServiceRequest") >= 1


async def test_a_patient_name_is_refused_and_no_patient_is_stored(
    api_client: AsyncClient, seeded: None, neo4j_driver: AsyncDriver
) -> None:
    body = {**CASE_BODY, "contained": [{**CASE_BODY["contained"][0], "name": [{"text": "x"}]}]}
    response = await api_client.post(
        "/fhir/ServiceRequest",
        json=body,
        headers={**token_headers(role=Role.ADVISOR), "Idempotency-Key": "case-open-name"},
    )
    assert response.status_code == 400
    assert await count_nodes(neo4j_driver, "Patient") == 0


async def test_an_executive_gets_the_same_404_as_an_unknown_id(
    api_client: AsyncClient, seeded: None
) -> None:
    response = await api_client.post(
        "/fhir/ServiceRequest",
        json=CASE_BODY,
        headers={**token_headers(role=Role.EXEC), "Idempotency-Key": "case-exec"},
    )
    assert response.status_code == 404


async def test_filter_options_offers_the_fitting_service_and_says_why_not_for_the_others(
    api_client: AsyncClient, seeded: None, neo4j_driver: AsyncDriver
) -> None:
    opened = await api_client.post(
        "/fhir/ServiceRequest",
        json=CASE_BODY,
        headers={**token_headers(role=Role.ADVISOR), "Idempotency-Key": "case-filter"},
    )
    case_id = opened.json()["id"]
    body = {
        "resourceType": "Parameters",
        "parameter": [
            {"name": "case", "valueReference": {"reference": f"ServiceRequest/{case_id}"}}
        ],
    }
    response = await api_client.post(
        "/fhir/HealthcareService/$filter-options",
        json=body,
        headers={**token_headers(role=Role.ADVISOR), "Idempotency-Key": "filter-1"},
    )
    assert response.status_code == 200, response.text
    parameters = response.json()["parameter"]
    options = [p for p in parameters if p["name"] == "option"]
    not_suitable = [p for p in parameters if p["name"] == "notSuitable"]
    assert [p for part in options for p in part["part"] if p.get("valueString") == "UCR West"]
    assert len(not_suitable) == 1
    assert any(p.get("valueString") == "not accepting" for p in not_suitable[0]["part"])
    assert await count_nodes(neo4j_driver, "AuditEvent") >= 2


async def test_a_put_needs_if_match_and_a_closed_case_is_a_conflict(
    api_client: AsyncClient, seeded: None
) -> None:
    opened = await api_client.post(
        "/fhir/ServiceRequest",
        json=CASE_BODY,
        headers={**token_headers(role=Role.ADVISOR), "Idempotency-Key": "case-put"},
    )
    case_id = opened.json()["id"]
    no_match = await api_client.put(
        f"/fhir/ServiceRequest/{case_id}",
        json=CASE_BODY,
        headers={**token_headers(role=Role.ADVISOR), "Idempotency-Key": "put-1"},
    )
    assert no_match.status_code == 428
    closed = await api_client.post(
        f"/fhir/ServiceRequest/{case_id}/$close",
        json={
            "resourceType": "Parameters",
            "parameter": [{"name": "outcome", "valueCode": "declined"}],
        },
        headers={**token_headers(role=Role.ADVISOR), "Idempotency-Key": "close-1"},
    )
    assert closed.status_code == 200, closed.text
    after = await api_client.put(
        f"/fhir/ServiceRequest/{case_id}",
        json=CASE_BODY,
        headers={
            **token_headers(role=Role.ADVISOR),
            "Idempotency-Key": "put-2",
            "If-Match": 'W/"case"',
        },
    )
    assert after.status_code == 409


async def test_advisor_phoned_stores_an_observation_by_the_advisor(
    api_client: AsyncClient, seeded: None, test_container: Any
) -> None:
    opened = await api_client.post(
        "/fhir/ServiceRequest",
        json=CASE_BODY,
        headers={**token_headers(role=Role.ADVISOR), "Idempotency-Key": "case-phone"},
    )
    case_id = opened.json()["id"]
    body = {
        "resourceType": "Parameters",
        "parameter": [
            {"name": "status", "valueCode": "accepting"},
            {"name": "value", "valueInteger": 3},
            {"name": "case", "valueReference": {"reference": f"ServiceRequest/{case_id}"}},
        ],
    }
    response = await api_client.post(
        f"/fhir/HealthcareService/{UCR_WEST}/$advisor-phoned",
        json=body,
        headers={**token_headers(role=Role.ADVISOR), "Idempotency-Key": "phone-1"},
    )
    assert response.status_code == 201, response.text
    observation_id = response.json()["id"]
    async with test_container.uow_factory() as uow:
        stored = await uow.capacity.get(observation_id)
    assert stored is not None
    assert stored.value == 3
    assert stored.source is ReportSource.ADVISOR_PHONED


async def test_close_leaves_no_postcode_and_no_needs(
    api_client: AsyncClient, seeded: None, test_container: Any
) -> None:
    opened = await api_client.post(
        "/fhir/ServiceRequest",
        json=CASE_BODY,
        headers={**token_headers(role=Role.ADVISOR), "Idempotency-Key": "case-close"},
    )
    case_id = opened.json()["id"]
    response = await api_client.post(
        f"/fhir/ServiceRequest/{case_id}/$close",
        json={
            "resourceType": "Parameters",
            "parameter": [
                {"name": "outcome", "valueCode": "accepted-and-booked"},
                {
                    "name": "destination",
                    "valueReference": {"reference": f"HealthcareService/{UCR_WEST}"},
                },
            ],
        },
        headers={**token_headers(role=Role.ADVISOR), "Idempotency-Key": "close-2"},
    )
    assert response.status_code == 200, response.text
    returned: dict[str, Any] = response.json()
    assert "reasonCode" not in returned
    assert "postalCode" not in str(returned)
    async with test_container.uow_factory() as uow:
        stored = await uow.cases.get(case_id)
    assert stored is not None
    assert stored.postcode is None and stored.needs == ()


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def route_state(api_app: Any, test_container: Any) -> None:
    """The BFF secret for the tokens and the cache the idempotent writes replay from (DEC-096)."""
    api_app.state.secrets = FixedSecretStore({BFF_SECRET_NAME: TEST_BFF_SECRET})
    api_app.state.cache = InMemoryCache(test_container.clock)


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def fresh_cases(neo4j_driver: AsyncDriver) -> AsyncIterator[None]:
    """Each case test starts from a wiped graph, so the case counts are its own."""
    await wipe(neo4j_driver)
    yield
