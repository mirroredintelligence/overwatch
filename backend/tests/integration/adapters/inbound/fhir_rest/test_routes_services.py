"""HealthcareService and capacity Observation endpoints over HTTP (R04), on the harness Neo4j.

UCR West and Ward A are seeded through the Neo4j repositories. What a test asserts is what was
really stored, read back through a fresh unit of work (DEC-004). Clock: Friday 23 October 2026,
14:12 London (13:12Z). Synthetic values only: no patient data.

The routes hold no rule: a report goes through ReportCapacity, so the tests here also show that its
rules (range, back-dating, flags, audit, outbox, replay) are reached through the endpoint.

Tenancy (transitional rule): the two-tenant tests are in test_routes_services_tenants.py.
"""

import json
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fhir.resources.R4B.bundle import Bundle
from fhir.resources.R4B.healthcareservice import HealthcareService
from fhir.resources.R4B.observation import Observation
from httpx import AsyncClient, Response
from neo4j import AsyncDriver

from diucs.adapters.inbound.fhir_rest.app import create_app
from diucs.adapters.inbound.fhir_rest.auth import BFF_SECRET_NAME
from diucs.adapters.inbound.fhir_rest.mapping import report_to_fhir
from diucs.adapters.outbound.audit_neo4j.audit_log import ensure_audit_head
from diucs.adapters.outbound.graph_store.capacity_repository import Neo4jCapacityRepository
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.adapters.testing.tokens import TEST_BFF_SECRET, issue_test_token
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.bootstrap.container import Container
from diucs.domain.codes import (
    Measure,
    ReportFlagReason,
    ReportSource,
    ReportType,
    Role,
    ScopeFlag,
    ServiceCategory,
    code_system_url,
)
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.registration import ScopeEntry
from diucs.domain.model.service import ServiceProfile
from tests.integration.adapters.inbound.fhir_rest.test_routes_board import WARD_A
from tests.integration.application.test_query_board import WEST
from tests.support.neo4j import count_nodes

pytestmark = pytest.mark.asyncio(loop_scope="session")

SERVICES = "/fhir/HealthcareService"
OBSERVATION = "/fhir/Observation"
LATEST_WEST = f"{OBSERVATION}?focus=HealthcareService/svc-ucr-west&_sort=-date&_count=1"
JSON_TYPE = {"Content-Type": "application/fhir+json"}
NOT_EDITED = "Reports are not edited. Send a new report."
MEASURE_SYSTEM = code_system_url("capacity-measure")
SOURCE_SYSTEM = code_system_url("report-source")
ALL_ROLES = tuple(Role)
SEARCH_ROLES = (Role.WALL, Role.ADVISOR, Role.CLINICAL, Role.LEAD, Role.EXEC, Role.OWNER)
NOT_SEARCH_ROLES = (Role.ANONYMOUS_LINK, Role.SUPPORT, Role.AUDIT)
NOT_REPORT_ROLES = (
    Role.ADVISOR,
    Role.CLINICAL,
    Role.OWNER,
    Role.EXEC,
    Role.WALL,
    Role.ANONYMOUS_LINK,
    Role.SUPPORT,
    Role.AUDIT,
)
WEST_PRIOR = CapacityReport(
    id="obs-west-1303",
    service_id="svc-ucr-west",
    value=3,
    measure=Measure.REFERRALS_ACCEPTABLE,
    effective_at=datetime(2026, 10, 23, 13, 3, tzinfo=UTC),
    source=ReportSource.TEXT,
    report_type=ReportType.NUMBER,
)


def bearer(role: Role, services: tuple[str, ...] = (), sub: str = "prac-1") -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_test_token(role, services, sub)}"}


def west_reporter() -> dict[str, str]:
    return bearer(Role.REPORTER, ("svc-ucr-west",), "prac-reporter-west")


def ward_reporter() -> dict[str, str]:
    return bearer(Role.REPORTER, ("svc-ward-a",), "prac-reporter-ward")


def lead() -> dict[str, str]:
    return bearer(Role.LEAD, (), "prac-lead-1")


def report_body(
    value: Any = 4,
    *,
    service: str = "svc-ucr-west",
    at: str | None = "2026-10-23T10:00:00Z",
    method: str = "app",
    measure: str = "referrals-acceptable",
    unit: str = "{referral}",
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "resourceType": "Observation",
        "status": "final",
        "code": {"coding": [{"system": MEASURE_SYSTEM, "code": measure}]},
        "focus": [{"reference": f"HealthcareService/{service}"}],
        "valueQuantity": {
            "value": value,
            "unit": "referrals",
            "system": "http://unitsofmeasure.org",
            "code": unit,
        },
        "method": {"coding": [{"system": SOURCE_SYSTEM, "code": method}]},
    }
    if at is not None:
        body["effectiveDateTime"] = at
    return body


async def post(
    client: AsyncClient,
    body: Any,
    headers: dict[str, str],
    key: str | None = "key-1",
) -> Response:
    sent = {**headers, **JSON_TYPE}
    if key is not None:
        sent["Idempotency-Key"] = key
    content = body if isinstance(body, str) else json.dumps(body)
    return await client.post(OBSERVATION, headers=sent, content=content)


@pytest_asyncio.fixture(loop_scope="session")
async def services_app(
    api_app: FastAPI, test_container: Container, neo4j_driver: AsyncDriver
) -> FastAPI:
    # test_container ran clean_graph, so the audit head is created after the wipe (lesson L133).
    await ensure_audit_head(neo4j_driver)
    api_app.state.secrets = FixedSecretStore({BFF_SECRET_NAME: TEST_BFF_SECRET})
    api_app.state.cache = InMemoryCache(test_container.clock)
    return api_app


@pytest.fixture
def clock(test_container: Container) -> FixedClock:
    assert isinstance(test_container.clock, FixedClock)
    return test_container.clock


@pytest.fixture
def factory(test_container: Container) -> UnitOfWorkFactory:
    return test_container.uow_factory


async def seed(
    factory: UnitOfWorkFactory,
    profiles: tuple[ServiceProfile, ...],
    reports: tuple[CapacityReport, ...] = (),
) -> None:
    async with factory() as uow:
        for profile in profiles:
            await uow.services.save(profile)
        for report in reports:
            await uow.capacity.add(report)
        await uow.commit()


@pytest_asyncio.fixture(loop_scope="session")
async def seeded(services_app: FastAPI, factory: UnitOfWorkFactory) -> None:
    await seed(factory, (WEST, WARD_A))


@pytest_asyncio.fixture(loop_scope="session")
async def seeded_with_report(services_app: FastAPI, factory: UnitOfWorkFactory) -> None:
    await seed(factory, (WEST, WARD_A), (WEST_PRIOR,))


def ids(bundle: dict[str, Any]) -> list[str]:
    return [entry["resource"]["id"] for entry in bundle.get("entry", [])]


async def latest(factory: UnitOfWorkFactory, service_id: str = "svc-ucr-west") -> CapacityReport:
    async with factory() as uow:
        report = await uow.capacity.latest(service_id)
    assert report is not None
    return report


async def seed_placeholder(factory: UnitOfWorkFactory) -> None:
    """A scope-list entry whose service has not registered: a minimal inactive HealthcareService
    with no profile (lesson L104)."""
    async with factory() as uow:
        await uow.scope.save_entry(
            ScopeEntry(
                service_id="svc-sdec-1",
                name="SDEC pilot",
                category=ServiceCategory.SAME_DAY_EMERGENCY_CARE,
                flag=ScopeFlag.IN_PILOT,
                date=date(2026, 10, 25),
                reason="",
            )
        )
        await uow.commit()


async def nothing_written(driver: AsyncDriver) -> None:
    for label in ("Observation", "AuditEvent", "OutboxMessage", "ReportFlag"):
        assert await count_nodes(driver, label) == 0, label


# CapabilityStatement


async def test_the_capability_statement_lists_both_resources_and_their_interactions(
    seeded: None, api_client: AsyncClient
) -> None:
    response = await api_client.get("/fhir/metadata")

    resources = {item["type"]: item for item in response.json()["rest"][0]["resource"]}
    assert [i["code"] for i in resources["HealthcareService"]["interaction"]] == [
        "read",
        "search-type",
    ]
    assert [o["name"] for o in resources["HealthcareService"]["operation"]] == [
        "board",
        "confirm-capacity",
    ]
    assert [i["code"] for i in resources["Observation"]["interaction"]] == [
        "read",
        "create",
        "search-type",
    ]
    assert "operation" not in resources["Observation"]


async def test_building_the_app_twice_registers_the_resources_once(
    seeded: None, test_container: Container, api_client: AsyncClient
) -> None:
    create_app(test_container)
    create_app(test_container)

    response = await api_client.get("/fhir/metadata")

    types = [item["type"] for item in response.json()["rest"][0]["resource"]]
    assert types.count("HealthcareService") == 1
    assert types.count("Observation") == 1


# HealthcareService search


async def test_search_active_true_returns_a_searchset_of_valid_services_by_name(
    seeded: None, api_client: AsyncClient
) -> None:
    response = await api_client.get(f"{SERVICES}?active=true", headers=west_reporter())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/fhir+json")
    body = response.json()
    Bundle.model_validate(body)
    assert body["type"] == "searchset"
    assert body["total"] == 2
    assert ids(body) == ["svc-ucr-west", "svc-ward-a"]
    for entry in body["entry"]:
        HealthcareService.model_validate(entry["resource"])
        assert entry["search"] == {"mode": "match"}
    west = body["entry"][0]["resource"]
    assert west["name"] == "UCR West"
    assert west["active"] is True


async def test_search_with_no_parameters_lists_the_active_services_too(
    seeded: None, api_client: AsyncClient
) -> None:
    response = await api_client.get(SERVICES, headers=west_reporter())

    assert response.status_code == 200
    assert ids(response.json()) == ["svc-ucr-west", "svc-ward-a"]


async def test_an_inactive_service_is_not_listed(
    seeded: None, api_client: AsyncClient, factory: UnitOfWorkFactory
) -> None:
    async with factory() as uow:
        await uow.services.save(
            ServiceProfile(**{**fields(WARD_A), "id": "svc-closed", "active": False})
        )
        await uow.commit()

    response = await api_client.get(SERVICES, headers=west_reporter())

    assert ids(response.json()) == ["svc-ucr-west", "svc-ward-a"]


def fields(profile: ServiceProfile) -> dict[str, Any]:
    return {name: getattr(profile, name) for name in profile.__dataclass_fields__}


async def test_active_false_is_refused_because_only_active_services_are_listed(
    seeded: None, api_client: AsyncClient
) -> None:
    response = await api_client.get(f"{SERVICES}?active=false", headers=west_reporter())

    assert response.status_code == 400
    assert response.json()["issue"][0]["code"] == "invalid"
    assert response.json()["issue"][0]["expression"] == ["active"]


@pytest.mark.parametrize("value", ["yes", "TRUE", "1", ""])
async def test_active_takes_true_only(seeded: None, api_client: AsyncClient, value: str) -> None:
    response = await api_client.get(f"{SERVICES}?active={value}", headers=west_reporter())

    assert response.status_code == 400
    assert response.json()["issue"][0]["expression"] == ["active"]


@pytest.mark.parametrize(
    "token",
    [
        "urgent-community-response",
        f"{code_system_url('service-category')}|urgent-community-response",
    ],
)
async def test_search_by_service_category_takes_a_code_or_a_system_and_code(
    seeded: None, api_client: AsyncClient, token: str
) -> None:
    response = await api_client.get(
        SERVICES, params={"service-category": token}, headers=west_reporter()
    )

    assert response.status_code == 200
    assert ids(response.json()) == ["svc-ucr-west"]
    assert response.json()["total"] == 1


async def test_a_category_with_no_service_is_an_empty_bundle(
    seeded: None, api_client: AsyncClient
) -> None:
    response = await api_client.get(
        SERVICES, params={"service-category": "same-day-emergency-care"}, headers=west_reporter()
    )

    assert response.status_code == 200
    assert response.json()["total"] == 0
    assert "entry" not in response.json()
    Bundle.model_validate(response.json())


@pytest.mark.parametrize(
    "token",
    [
        "free-chairs",
        "https://example.org/other|urgent-community-response",
        f"{code_system_url('service-category')}|",
        "|",
    ],
)
async def test_an_unknown_category_is_400_and_the_value_is_not_echoed(
    seeded: None, api_client: AsyncClient, token: str
) -> None:
    response = await api_client.get(
        SERVICES, params={"service-category": token}, headers=west_reporter()
    )

    assert response.status_code == 400
    assert response.json()["issue"][0]["expression"] == ["service-category"]
    assert "free-chairs" not in response.text
    assert "example.org" not in response.text


@pytest.mark.parametrize("form", ["{tenant}", "Organization/{tenant}"])
async def test_search_by_the_organisation_of_the_caller_lists_its_services(
    seeded: None, api_client: AsyncClient, tenant_id: str, form: str
) -> None:
    response = await api_client.get(
        SERVICES, params={"organization": form.format(tenant=tenant_id)}, headers=lead()
    )

    assert response.status_code == 200
    assert ids(response.json()) == ["svc-ucr-west", "svc-ward-a"]


@pytest.mark.parametrize("value", ["some-other-org", "Organization/some-other-org", "net-x"])
async def test_search_by_another_organisation_is_an_empty_bundle(
    seeded: None, api_client: AsyncClient, value: str
) -> None:
    response = await api_client.get(SERVICES, params={"organization": value}, headers=lead())

    assert response.status_code == 200
    assert response.json()["total"] == 0
    assert "entry" not in response.json()


@pytest.mark.parametrize("value", ["", "Patient/x", "Organization/", "a b", "x" * 65, "a/b"])
async def test_a_malformed_organisation_is_400(
    seeded: None, api_client: AsyncClient, value: str
) -> None:
    response = await api_client.get(SERVICES, params={"organization": value}, headers=lead())

    assert response.status_code == 400
    assert response.json()["issue"][0]["expression"] == ["organization"]


async def test_filters_combine(seeded: None, api_client: AsyncClient, tenant_id: str) -> None:
    response = await api_client.get(
        SERVICES,
        params={
            "active": "true",
            "service-category": "inpatient-beds",
            "organization": tenant_id,
        },
        headers=lead(),
    )

    assert ids(response.json()) == ["svc-ward-a"]


async def test_search_is_paged_with_a_next_link_that_keeps_the_filters(
    seeded: None, api_client: AsyncClient
) -> None:
    first = await api_client.get(SERVICES, params={"_count": "1"}, headers=lead())

    body = first.json()
    assert ids(body) == ["svc-ucr-west"]
    assert body["total"] == 2
    links = {link["relation"]: link["url"] for link in body["link"]}
    assert set(links) == {"self", "next"}
    assert parse_qs(urlsplit(links["self"]).query) == {"_count": ["1"]}
    assert urlsplit(links["next"]).path == "/fhir/HealthcareService"
    assert parse_qs(urlsplit(links["next"]).query) == {"_count": ["1"], "_offset": ["1"]}

    second = await api_client.get(links["next"], headers=lead())

    assert ids(second.json()) == ["svc-ward-a"]
    assert second.json()["total"] == 2
    assert {link["relation"] for link in second.json()["link"]} == {"self"}


async def test_the_next_link_carries_the_filters_it_was_asked_with(
    seeded: None, api_client: AsyncClient, factory: UnitOfWorkFactory, tenant_id: str
) -> None:
    await seed(
        factory, (ServiceProfile(**{**fields(WARD_A), "id": "svc-ward-b", "name": "Ward B"}),)
    )

    response = await api_client.get(
        SERVICES,
        params={"service-category": "inpatient-beds", "organization": tenant_id, "_count": "1"},
        headers=lead(),
    )

    links = {link["relation"]: link["url"] for link in response.json()["link"]}
    assert parse_qs(urlsplit(links["next"]).query) == {
        "service-category": ["inpatient-beds"],
        "organization": [tenant_id],
        "_count": ["1"],
        "_offset": ["1"],
    }


async def test_an_offset_past_the_end_is_an_empty_page_with_the_total(
    seeded: None, api_client: AsyncClient
) -> None:
    response = await api_client.get(SERVICES, params={"_offset": "5"}, headers=lead())

    assert response.status_code == 200
    assert response.json()["total"] == 2
    assert "entry" not in response.json()
    assert {link["relation"] for link in response.json()["link"]} == {"self"}


async def test_the_page_size_is_at_most_100(seeded: None, api_client: AsyncClient) -> None:
    allowed = await api_client.get(SERVICES, params={"_count": "100"}, headers=lead())
    refused = await api_client.get(SERVICES, params={"_count": "101"}, headers=lead())

    assert allowed.status_code == 200
    assert refused.status_code == 400
    assert refused.json()["issue"][0]["expression"] == ["_count"]


@pytest.mark.parametrize("value", ["0", "-1", "abc", "1.5", "", " 1"])
async def test_a_bad_count_is_400(seeded: None, api_client: AsyncClient, value: str) -> None:
    response = await api_client.get(SERVICES, params={"_count": value}, headers=lead())

    assert response.status_code == 400
    assert response.json()["issue"][0]["expression"] == ["_count"]


@pytest.mark.parametrize("value", ["-1", "abc", "1.5", ""])
async def test_a_bad_offset_is_400(seeded: None, api_client: AsyncClient, value: str) -> None:
    response = await api_client.get(SERVICES, params={"_offset": value}, headers=lead())

    assert response.status_code == 400
    assert response.json()["issue"][0]["expression"] == ["_offset"]


async def test_an_unknown_or_repeated_parameter_is_400_and_its_name_is_not_echoed(
    seeded: None, api_client: AsyncClient
) -> None:
    unknown = await api_client.get(f"{SERVICES}?zz-name=UCR", headers=lead())
    repeated = await api_client.get(f"{SERVICES}?_count=1&_count=2", headers=lead())

    assert unknown.status_code == 400
    assert unknown.json()["issue"][0]["expression"] == ["parameters"]
    assert "zz-name" not in unknown.text
    assert repeated.status_code == 400
    assert repeated.json()["issue"][0]["expression"] == ["_count"]


@pytest.mark.parametrize("role", ALL_ROLES)
async def test_any_authenticated_role_may_search_services(
    seeded: None, api_client: AsyncClient, role: Role
) -> None:
    response = await api_client.get(SERVICES, headers=bearer(role, ("svc-ucr-west",)))

    assert response.status_code == 200


async def test_search_without_a_token_is_login(seeded: None, api_client: AsyncClient) -> None:
    response = await api_client.get(SERVICES)

    assert response.status_code == 401
    assert response.json()["issue"][0]["code"] == "login"


async def test_search_writes_nothing(
    seeded: None, api_client: AsyncClient, neo4j_driver: AsyncDriver
) -> None:
    await api_client.get(SERVICES, headers=lead())

    await nothing_written(neo4j_driver)


# HealthcareService read


async def test_read_by_id_returns_the_service_with_an_etag(
    seeded: None, api_client: AsyncClient
) -> None:
    response = await api_client.get(f"{SERVICES}/svc-ucr-west", headers=west_reporter())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/fhir+json")
    assert response.headers["etag"] == 'W/"1"'
    body = response.json()
    HealthcareService.model_validate(body)
    assert body["id"] == "svc-ucr-west"
    assert body["name"] == "UCR West"
    assert body["meta"]["versionId"] == "1"


async def test_the_etag_follows_the_stored_version(
    seeded: None, api_client: AsyncClient, factory: UnitOfWorkFactory
) -> None:
    await seed(factory, (ServiceProfile(**{**fields(WEST), "name": "UCR West (renamed)"}),))

    response = await api_client.get(f"{SERVICES}/svc-ucr-west", headers=west_reporter())

    assert response.headers["etag"] == 'W/"2"'
    assert response.json()["meta"]["versionId"] == "2"
    assert response.json()["name"] == "UCR West (renamed)"


async def test_any_role_reads_any_service_by_id(seeded: None, api_client: AsyncClient) -> None:
    for role in ALL_ROLES:
        response = await api_client.get(f"{SERVICES}/svc-ward-a", headers=bearer(role, ()))

        assert response.status_code == 200, role


async def test_an_unknown_id_is_404_not_found(seeded: None, api_client: AsyncClient) -> None:
    response = await api_client.get(f"{SERVICES}/svc-nowhere", headers=lead())

    assert response.status_code == 404
    assert response.json()["resourceType"] == "OperationOutcome"
    assert response.json()["issue"][0]["code"] == "not-found"


@pytest.mark.parametrize("service_id", ["a b", "x" * 65, "a%2Fb", "svc!"])
async def test_a_malformed_id_is_the_same_404(
    seeded: None, api_client: AsyncClient, service_id: str
) -> None:
    unknown = await api_client.get(f"{SERVICES}/svc-nowhere", headers=lead())
    response = await api_client.get(f"{SERVICES}/{service_id}", headers=lead())

    assert response.status_code == 404
    assert response.json() == unknown.json()


async def test_a_service_that_has_not_registered_yet_is_404_and_is_not_listed(
    seeded: None, api_client: AsyncClient, factory: UnitOfWorkFactory
) -> None:
    await seed_placeholder(factory)

    unknown = await api_client.get(f"{SERVICES}/svc-nowhere", headers=lead())
    response = await api_client.get(f"{SERVICES}/svc-sdec-1", headers=lead())
    listed = await api_client.get(SERVICES, headers=lead())

    assert response.status_code == 404
    assert response.json() == unknown.json()
    assert "svc-sdec-1" not in ids(listed.json())


async def test_read_by_id_without_a_token_is_login(seeded: None, api_client: AsyncClient) -> None:
    response = await api_client.get(f"{SERVICES}/svc-ucr-west")

    assert response.status_code == 401


async def test_the_board_route_is_not_taken_by_the_id_route(
    seeded: None, api_client: AsyncClient
) -> None:
    response = await api_client.get(f"{SERVICES}/$board", headers=bearer(Role.ADVISOR))

    assert response.status_code == 200
    assert response.json()["resourceType"] == "Parameters"


# POST /fhir/Observation


async def test_a_reporter_posts_a_report_and_it_is_stored_and_read_back_the_same(
    seeded: None,
    api_client: AsyncClient,
    factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
) -> None:
    response = await post(api_client, report_body(4), west_reporter())

    assert response.status_code == 201
    assert response.headers["content-type"].startswith("application/fhir+json")
    body = response.json()
    Observation.model_validate(body)
    assert response.headers["location"] == f"/fhir/Observation/{body['id']}"
    stored = await latest(factory)
    assert stored.id == body["id"]
    assert stored.value == 4
    assert stored.source is ReportSource.APP
    assert stored.report_type is ReportType.NUMBER
    assert stored.measure is Measure.REFERRALS_ACCEPTABLE
    assert stored.effective_at == datetime(2026, 10, 23, 10, 0, tzinfo=UTC)
    assert body == report_to_fhir(stored)
    assert await count_nodes(neo4j_driver, "Observation") == 1


async def test_the_report_has_its_audit_entry_and_outbox_message_from_the_use_case(
    seeded: None, api_client: AsyncClient, neo4j_driver: AsyncDriver
) -> None:
    await post(api_client, report_body(4), west_reporter())

    assert await count_nodes(neo4j_driver, "AuditEvent") == 1
    assert await count_nodes(neo4j_driver, "OutboxMessage") >= 1


async def test_an_offset_effective_time_is_stored_as_the_utc_instant(
    seeded: None, api_client: AsyncClient, factory: UnitOfWorkFactory
) -> None:
    response = await post(
        api_client, report_body(4, at="2026-10-23T11:00:00+01:00"), west_reporter()
    )

    assert response.status_code == 201
    assert response.json()["effectiveDateTime"] == "2026-10-23T10:00:00Z"
    assert (await latest(factory)).effective_at == datetime(2026, 10, 23, 10, 0, tzinfo=UTC)


async def test_a_lead_posts_an_advisor_phoned_report_for_any_service(
    seeded: None, api_client: AsyncClient, factory: UnitOfWorkFactory
) -> None:
    response = await post(api_client, report_body(2, method="advisor-phoned"), lead())

    assert response.status_code == 201
    stored = await latest(factory)
    assert stored.value == 2
    assert stored.source is ReportSource.ADVISOR_PHONED


async def test_a_lead_cannot_post_as_the_app_and_a_reporter_cannot_post_as_the_advisor(
    seeded: None, api_client: AsyncClient, neo4j_driver: AsyncDriver
) -> None:
    unknown = await api_client.get(f"{SERVICES}/svc-nowhere", headers=lead())
    as_app = await post(api_client, report_body(2, method="app"), lead())
    as_advisor = await post(
        api_client, report_body(2, method="advisor-phoned"), west_reporter(), key="key-2"
    )

    # The use case refuses (check_may_report) and the route answers with the not-found body.
    assert as_app.status_code == 404
    assert as_app.json() == unknown.json()
    assert as_advisor.status_code == 404
    assert as_advisor.json() == unknown.json()
    await nothing_written(neo4j_driver)


async def test_a_reporter_for_another_service_gets_the_same_404_as_an_unknown_service(
    seeded: None, api_client: AsyncClient, neo4j_driver: AsyncDriver
) -> None:
    other = await post(
        api_client,
        report_body(4, service="svc-ward-a", measure="free-beds", unit="{bed}"),
        west_reporter(),
    )
    nowhere = await post(
        api_client, report_body(4, service="svc-nowhere"), west_reporter(), key="key-2"
    )

    assert other.status_code == 404
    assert other.json()["issue"][0]["code"] == "not-found"
    assert other.json() == nowhere.json()
    await nothing_written(neo4j_driver)


async def test_a_lead_posting_for_an_unknown_service_gets_not_found(
    seeded: None, api_client: AsyncClient, neo4j_driver: AsyncDriver
) -> None:
    unknown = await api_client.get(f"{SERVICES}/svc-nowhere", headers=lead())
    response = await post(
        api_client, report_body(4, service="svc-nowhere", method="advisor-phoned"), lead()
    )

    assert response.status_code == 404
    assert response.json() == unknown.json()
    await nothing_written(neo4j_driver)


async def test_an_inactive_service_takes_no_report(
    seeded: None,
    api_client: AsyncClient,
    factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
) -> None:
    await seed(factory, (ServiceProfile(**{**fields(WEST), "active": False}),))

    response = await post(api_client, report_body(4, method="advisor-phoned"), lead())

    assert response.status_code == 404
    await nothing_written(neo4j_driver)


async def test_a_service_that_has_not_registered_takes_no_report_and_reads_as_not_found(
    seeded: None,
    api_client: AsyncClient,
    factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
) -> None:
    await seed_placeholder(factory)

    response = await post(
        api_client, report_body(4, service="svc-sdec-1", method="advisor-phoned"), lead()
    )

    assert response.status_code == 404
    await nothing_written(neo4j_driver)


@pytest.mark.parametrize("role", NOT_REPORT_ROLES)
async def test_any_other_role_gets_the_not_found_answer_and_nothing_is_stored(
    seeded: None, api_client: AsyncClient, neo4j_driver: AsyncDriver, role: Role
) -> None:
    unknown = await api_client.get(f"{SERVICES}/svc-nowhere", headers=lead())
    response = await post(api_client, report_body(4), bearer(role, ("svc-ucr-west",)))

    assert response.status_code == 404
    assert response.json() == unknown.json()
    await nothing_written(neo4j_driver)


async def test_no_token_cannot_post(
    seeded: None, api_client: AsyncClient, neo4j_driver: AsyncDriver
) -> None:
    response = await post(api_client, report_body(4), {})

    assert response.status_code == 401
    assert response.json()["issue"][0]["code"] == "login"
    await nothing_written(neo4j_driver)


async def test_a_missing_focus_is_400_invalid_naming_the_element_and_stores_nothing(
    seeded: None, api_client: AsyncClient, neo4j_driver: AsyncDriver
) -> None:
    body = report_body(4)
    del body["focus"]

    response = await post(api_client, body, west_reporter())

    assert response.status_code == 400
    issue = response.json()["issue"][0]
    assert issue["code"] == "invalid"
    assert issue["expression"] == ["Observation.focus"]
    await nothing_written(neo4j_driver)


@pytest.mark.parametrize("value", [4.5, 4.0, "4", True, None])
async def test_a_value_that_is_not_a_whole_number_is_400_and_stores_nothing(
    seeded: None, api_client: AsyncClient, neo4j_driver: AsyncDriver, value: Any
) -> None:
    response = await post(api_client, report_body(value), west_reporter())

    assert response.status_code == 400
    assert response.json()["issue"][0]["expression"] == ["Observation.valueQuantity.value"]
    assert "4.5" not in response.text
    await nothing_written(neo4j_driver)


@pytest.mark.parametrize("value", [-1, 1000])
async def test_a_figure_outside_zero_to_999_is_refused_by_the_use_case_and_stores_nothing(
    seeded: None, api_client: AsyncClient, neo4j_driver: AsyncDriver, value: int
) -> None:
    response = await post(api_client, report_body(value), west_reporter())

    assert response.status_code == 400
    assert response.json()["issue"][0]["expression"] == ["Observation.valueQuantity.value"]
    await nothing_written(neo4j_driver)


async def test_zero_is_a_report_it_means_closed_to_referrals(
    seeded: None, api_client: AsyncClient, factory: UnitOfWorkFactory
) -> None:
    response = await post(api_client, report_body(0), west_reporter())

    assert response.status_code == 201
    assert (await latest(factory)).is_closed


async def test_the_code_must_be_the_measure_of_the_service(
    seeded: None, api_client: AsyncClient, neo4j_driver: AsyncDriver
) -> None:
    response = await post(
        api_client, report_body(4, measure="free-beds", unit="{bed}"), west_reporter()
    )

    assert response.status_code == 400
    assert response.json()["issue"][0]["expression"] == ["Observation.code"]
    await nothing_written(neo4j_driver)


async def test_the_unit_must_be_the_annotation_of_the_measure(
    seeded: None, api_client: AsyncClient, neo4j_driver: AsyncDriver
) -> None:
    response = await post(api_client, report_body(4, unit="{bed}"), west_reporter())

    assert response.status_code == 400
    assert response.json()["issue"][0]["expression"] == ["Observation.valueQuantity.code"]
    await nothing_written(neo4j_driver)


@pytest.mark.parametrize("method", ["text", "link", "email", "feed", "carrier-pigeon"])
async def test_a_source_the_api_does_not_carry_is_400(
    seeded: None, api_client: AsyncClient, neo4j_driver: AsyncDriver, method: str
) -> None:
    response = await post(api_client, report_body(4, method=method), west_reporter())

    assert response.status_code == 400
    assert response.json()["issue"][0]["expression"] == ["Observation.method"]
    await nothing_written(neo4j_driver)


@pytest.mark.parametrize(
    ("body", "expression"),
    [
        ("{not json", "Observation"),
        ("[]", "Observation"),
        ("", "Observation"),
        ("null", "Observation"),
    ],
)
async def test_a_body_that_is_not_a_json_object_is_400(
    seeded: None,
    api_client: AsyncClient,
    neo4j_driver: AsyncDriver,
    body: str,
    expression: str,
) -> None:
    response = await post(api_client, body, west_reporter())

    assert response.status_code == 400
    assert response.json()["issue"][0]["expression"] == [expression]
    await nothing_written(neo4j_driver)


async def test_a_wrong_status_and_a_wrong_resource_type_are_400(
    seeded: None, api_client: AsyncClient, neo4j_driver: AsyncDriver
) -> None:
    preliminary = {**report_body(4), "status": "preliminary"}
    patient = {**report_body(4), "resourceType": "Patient"}

    first = await post(api_client, preliminary, west_reporter())
    second = await post(api_client, patient, west_reporter(), key="key-2")

    assert first.json()["issue"][0]["expression"] == ["Observation.status"]
    assert second.json()["issue"][0]["expression"] == ["Observation.resourceType"]
    await nothing_written(neo4j_driver)


@pytest.mark.parametrize(
    "at", [None, "2026-10-23", "2026-10-23T10:00:00", "2026-10-23T10:00Z", "yesterday"]
)
async def test_the_effective_time_is_required_and_needs_a_zone(
    seeded: None, api_client: AsyncClient, neo4j_driver: AsyncDriver, at: str | None
) -> None:
    response = await post(api_client, report_body(4, at=at), west_reporter())

    assert response.status_code == 400
    assert response.json()["issue"][0]["expression"] == ["Observation.effectiveDateTime"]
    await nothing_written(neo4j_driver)


async def test_a_report_dated_after_now_is_refused_by_the_use_case(
    seeded: None, api_client: AsyncClient, neo4j_driver: AsyncDriver
) -> None:
    response = await post(api_client, report_body(4, at="2026-10-23T13:13:00Z"), west_reporter())

    assert response.status_code == 400
    assert response.json()["issue"][0]["expression"] == ["Observation.effectiveDateTime"]
    await nothing_written(neo4j_driver)


async def test_a_number_dated_before_the_latest_confirmed_figure_is_refused_by_the_use_case(
    seeded_with_report: None,
    api_client: AsyncClient,
    neo4j_driver: AsyncDriver,
    factory: UnitOfWorkFactory,
) -> None:
    confirmed = await api_client.post(
        f"{SERVICES}/svc-ucr-west/$confirm-capacity",
        headers={**west_reporter(), **JSON_TYPE, "Idempotency-Key": "confirm-1"},
        content=json.dumps({"resourceType": "Parameters"}),
    )
    assert confirmed.status_code == 201

    response = await post(api_client, report_body(5, at="2026-10-23T13:05:00Z"), west_reporter())

    assert response.status_code == 400
    assert response.json()["issue"][0]["expression"] == ["Observation.effectiveDateTime"]
    assert await count_nodes(neo4j_driver, "Observation") == 2  # the prior figure and the confirm


@pytest.mark.parametrize(
    "extra",
    [
        {"derivedFrom": [{"reference": "Observation/obs-west-1303"}]},
        {"performer": [{"reference": "PractitionerRole/role-1"}]},
        {"component": []},
    ],
)
async def test_an_element_the_report_does_not_take_is_400_and_stores_nothing(
    seeded: None, api_client: AsyncClient, neo4j_driver: AsyncDriver, extra: dict[str, Any]
) -> None:
    response = await post(api_client, {**report_body(4), **extra}, west_reporter())

    assert response.status_code == 400
    assert response.json()["issue"][0]["expression"] == ["Observation"]
    await nothing_written(neo4j_driver)


async def test_a_report_for_a_phoned_figure_that_differs_raises_the_flag_in_the_same_unit(
    seeded: None,
    api_client: AsyncClient,
    factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
) -> None:
    phoned = await post(
        api_client, report_body(3, at="2026-10-23T10:00:00Z", method="advisor-phoned"), lead()
    )
    sent = await post(
        api_client, report_body(5, at="2026-10-23T10:20:00Z"), west_reporter(), key="key-2"
    )

    assert phoned.status_code == 201
    assert sent.status_code == 201
    async with factory() as uow:
        flags = await uow.flags.open_report_flags("svc-ucr-west")
    assert [flag.reason for flag in flags] == [ReportFlagReason.DIFFERS_FROM_PHONED]
    assert flags[0].report_id == sent.json()["id"]
    assert await count_nodes(neo4j_driver, "Observation") == 2


async def test_a_failed_post_leaves_no_partial_write(
    seeded: None, api_client: AsyncClient, neo4j_driver: AsyncDriver
) -> None:
    await post(api_client, report_body(1000), west_reporter())

    await nothing_written(neo4j_driver)


# Idempotency


async def test_a_missing_idempotency_key_is_400_and_stores_nothing(
    seeded: None, api_client: AsyncClient, neo4j_driver: AsyncDriver
) -> None:
    response = await post(api_client, report_body(4), west_reporter(), key=None)

    assert response.status_code == 400
    assert response.json()["issue"][0]["code"] == "required"
    await nothing_written(neo4j_driver)


async def test_an_invalid_idempotency_key_is_400(
    seeded: None, api_client: AsyncClient, neo4j_driver: AsyncDriver
) -> None:
    response = await post(api_client, report_body(4), west_reporter(), key="has space")

    assert response.status_code == 400
    assert response.json()["issue"][0]["code"] == "invalid"
    await nothing_written(neo4j_driver)


async def test_the_same_key_twice_stores_one_report_and_answers_the_repeat_from_the_cache(
    seeded: None, api_client: AsyncClient, neo4j_driver: AsyncDriver
) -> None:
    first = await post(api_client, report_body(4), west_reporter())
    second = await post(api_client, report_body(4), west_reporter())

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json() == first.json()
    assert second.headers["location"] == first.headers["location"]
    assert second.headers["idempotent-replay"] == "true"
    assert "idempotent-replay" not in first.headers
    assert await count_nodes(neo4j_driver, "Observation") == 1
    assert await count_nodes(neo4j_driver, "AuditEvent") == 1


async def test_the_stored_key_answers_the_repeat_after_the_cache_is_lost(
    seeded: None,
    api_app: FastAPI,
    api_client: AsyncClient,
    clock: FixedClock,
    neo4j_driver: AsyncDriver,
) -> None:
    first = await post(api_client, report_body(4), west_reporter())
    api_app.state.cache = InMemoryCache(clock)

    second = await post(api_client, report_body(4), west_reporter())

    assert second.status_code == 201
    assert second.json() == first.json()
    assert await count_nodes(neo4j_driver, "Observation") == 1
    assert await count_nodes(neo4j_driver, "AuditEvent") == 1


async def test_the_same_key_with_another_body_is_422_from_the_cache(
    seeded: None, api_client: AsyncClient, neo4j_driver: AsyncDriver
) -> None:
    await post(api_client, report_body(4), west_reporter())

    second = await post(api_client, report_body(5), west_reporter())

    assert second.status_code == 422
    assert second.json()["issue"][0]["code"] == "conflict"
    assert await count_nodes(neo4j_driver, "Observation") == 1


async def test_the_same_key_with_another_body_is_409_from_the_store_after_the_cache_is_lost(
    seeded: None,
    api_app: FastAPI,
    api_client: AsyncClient,
    clock: FixedClock,
    neo4j_driver: AsyncDriver,
) -> None:
    await post(api_client, report_body(4), west_reporter())
    api_app.state.cache = InMemoryCache(clock)

    second = await post(api_client, report_body(5), west_reporter())

    assert second.status_code == 409
    assert second.json()["issue"][0]["code"] == "conflict"
    assert await count_nodes(neo4j_driver, "Observation") == 1


async def test_a_refused_post_is_not_cached_so_it_can_be_sent_again_corrected(
    seeded: None, api_client: AsyncClient, factory: UnitOfWorkFactory
) -> None:
    refused = await post(api_client, report_body(1000), west_reporter())
    corrected = await post(api_client, report_body(4), west_reporter())

    assert refused.status_code == 400
    assert corrected.status_code == 201
    assert (await latest(factory)).value == 4


async def test_a_key_used_for_a_confirmation_is_refused_for_a_report_and_writes_nothing_more(
    seeded_with_report: None, api_client: AsyncClient, neo4j_driver: AsyncDriver
) -> None:
    confirmed = await api_client.post(
        f"{SERVICES}/svc-ucr-west/$confirm-capacity",
        headers={**west_reporter(), **JSON_TYPE, "Idempotency-Key": "shared-key"},
        content=json.dumps({"resourceType": "Parameters"}),
    )
    assert confirmed.status_code == 201

    response = await post(api_client, report_body(5), west_reporter(), key="shared-key")

    assert response.status_code == 409
    assert await count_nodes(neo4j_driver, "Observation") == 2


# Reports are never edited


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE"])
async def test_a_report_is_never_edited_or_deleted(
    seeded_with_report: None,
    api_client: AsyncClient,
    neo4j_driver: AsyncDriver,
    method: str,
) -> None:
    response = await api_client.request(
        method,
        f"{OBSERVATION}/obs-west-1303",
        headers={**west_reporter(), **JSON_TYPE},
        content=json.dumps(report_body(9)),
    )

    assert response.status_code == 405
    issue = response.json()["issue"][0]
    assert issue["code"] == "not-supported"
    assert issue["diagnostics"] == NOT_EDITED
    assert response.headers["allow"] == "GET"
    assert await count_nodes(neo4j_driver, "Observation") == 1
    assert (await api_client.get(LATEST_WEST, headers=west_reporter())).json()["entry"][0][
        "resource"
    ]["valueQuantity"]["value"] == 3


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE"])
async def test_the_405_does_not_depend_on_the_id_existing_or_the_caller(
    seeded: None, api_client: AsyncClient, method: str
) -> None:
    response = await api_client.request(method, f"{OBSERVATION}/x", headers=JSON_TYPE, content="{}")

    assert response.status_code == 405
    assert response.json()["issue"][0]["diagnostics"] == NOT_EDITED


# Observation search: the latest report


async def test_the_latest_search_returns_the_newest_report_in_a_searchset(
    seeded_with_report: None, api_client: AsyncClient, factory: UnitOfWorkFactory
) -> None:
    response = await api_client.get(LATEST_WEST, headers=west_reporter())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/fhir+json")
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    Bundle.model_validate(body)
    assert body["type"] == "searchset"
    assert body["total"] == 1
    assert body["entry"] == [
        {"resource": report_to_fhir(await latest(factory)), "search": {"mode": "match"}}
    ]
    Observation.model_validate(body["entry"][0]["resource"])


async def test_with_no_report_the_search_is_an_empty_bundle(
    seeded: None, api_client: AsyncClient
) -> None:
    response = await api_client.get(LATEST_WEST, headers=west_reporter())

    assert response.status_code == 200
    assert response.json()["total"] == 0
    assert "entry" not in response.json()
    Bundle.model_validate(response.json())


async def test_two_posts_and_the_latest_search_returns_the_later_one(
    seeded: None, api_client: AsyncClient
) -> None:
    await post(api_client, report_body(3, at="2026-10-23T10:00:00Z"), west_reporter(), key="k-1")
    await post(api_client, report_body(6, at="2026-10-23T10:12:00Z"), west_reporter(), key="k-2")

    response = await api_client.get(LATEST_WEST, headers=west_reporter())

    resource = response.json()["entry"][0]["resource"]
    assert resource["effectiveDateTime"] == "2026-10-23T10:12:00Z"
    assert resource["valueQuantity"]["value"] == 6


async def test_the_latest_is_by_effective_time_not_by_arrival(
    seeded: None, api_client: AsyncClient
) -> None:
    await post(api_client, report_body(6, at="2026-10-23T10:12:00Z"), west_reporter(), key="k-1")
    await post(api_client, report_body(3, at="2026-10-23T10:00:00Z"), west_reporter(), key="k-2")

    response = await api_client.get(LATEST_WEST, headers=west_reporter())

    assert response.json()["entry"][0]["resource"]["valueQuantity"]["value"] == 6


@pytest.mark.parametrize(
    "query",
    [
        "focus=HealthcareService/svc-ucr-west",
        "focus=svc-ucr-west",
        "focus=HealthcareService/svc-ucr-west&_sort=-date",
        "focus=HealthcareService/svc-ucr-west&_count=1",
    ],
)
async def test_the_sort_and_count_are_optional_and_the_focus_may_be_a_bare_id(
    seeded_with_report: None, api_client: AsyncClient, query: str
) -> None:
    response = await api_client.get(f"{OBSERVATION}?{query}", headers=west_reporter())

    assert response.status_code == 200
    assert response.json()["total"] == 1


@pytest.mark.parametrize("role", SEARCH_ROLES)
async def test_the_board_roles_search_the_latest_report_of_any_service(
    seeded_with_report: None, api_client: AsyncClient, role: Role
) -> None:
    response = await api_client.get(LATEST_WEST, headers=bearer(role, ()))

    assert response.status_code == 200
    assert response.json()["total"] == 1


@pytest.mark.parametrize("role", NOT_SEARCH_ROLES)
async def test_the_other_roles_get_the_not_found_answer(
    seeded_with_report: None, api_client: AsyncClient, role: Role
) -> None:
    unknown = await api_client.get(f"{SERVICES}/svc-nowhere", headers=lead())
    response = await api_client.get(LATEST_WEST, headers=bearer(role, ("svc-ucr-west",)))

    assert response.status_code == 404
    assert response.json() == unknown.json()


async def test_a_reporter_searching_another_service_gets_the_same_404_as_an_unknown_service(
    seeded_with_report: None, api_client: AsyncClient
) -> None:
    other = await api_client.get(LATEST_WEST, headers=ward_reporter())
    nowhere = await api_client.get(
        f"{OBSERVATION}?focus=HealthcareService/svc-nowhere&_sort=-date&_count=1",
        headers=ward_reporter(),
    )

    assert other.status_code == 404
    assert other.json()["issue"][0]["code"] == "not-found"
    assert other.json() == nowhere.json()


async def test_an_unknown_service_is_404_for_a_lead_too(
    seeded: None, api_client: AsyncClient
) -> None:
    response = await api_client.get(
        f"{OBSERVATION}?focus=HealthcareService/svc-nowhere", headers=lead()
    )

    assert response.status_code == 404


async def test_a_missing_focus_is_400_naming_the_parameter(
    seeded: None, api_client: AsyncClient
) -> None:
    response = await api_client.get(f"{OBSERVATION}?_sort=-date&_count=1", headers=lead())

    assert response.status_code == 400
    assert response.json()["issue"][0]["code"] == "invalid"
    assert response.json()["issue"][0]["expression"] == ["focus"]


@pytest.mark.parametrize(
    "focus", ["Patient/abc", "HealthcareService/", "HealthcareService/a b", "", "a/b/c", "x" * 65]
)
async def test_a_malformed_focus_is_400(seeded: None, api_client: AsyncClient, focus: str) -> None:
    response = await api_client.get(OBSERVATION, params={"focus": focus}, headers=lead())

    assert response.status_code == 400
    assert response.json()["issue"][0]["expression"] == ["focus"]


@pytest.mark.parametrize("sort", ["date", "-value", "-date,date", ""])
async def test_only_newest_first_is_supported(
    seeded: None, api_client: AsyncClient, sort: str
) -> None:
    response = await api_client.get(
        OBSERVATION,
        params={"focus": "HealthcareService/svc-ucr-west", "_sort": sort},
        headers=lead(),
    )

    assert response.status_code == 400
    assert response.json()["issue"][0]["expression"] == ["_sort"]


@pytest.mark.parametrize("count", ["0", "2", "50", "-1", "abc", ""])
async def test_only_the_latest_report_is_returned_so_the_count_is_one(
    seeded: None, api_client: AsyncClient, count: str
) -> None:
    response = await api_client.get(
        OBSERVATION,
        params={"focus": "HealthcareService/svc-ucr-west", "_count": count},
        headers=lead(),
    )

    assert response.status_code == 400
    assert response.json()["issue"][0]["expression"] == ["_count"]


async def test_an_unknown_or_repeated_search_parameter_is_400(
    seeded: None, api_client: AsyncClient
) -> None:
    unknown = await api_client.get(
        f"{OBSERVATION}?focus=HealthcareService/svc-ucr-west&status=final", headers=lead()
    )
    repeated = await api_client.get(
        f"{OBSERVATION}?focus=HealthcareService/svc-ucr-west&focus=HealthcareService/svc-ward-a",
        headers=lead(),
    )

    assert unknown.status_code == 400
    assert unknown.json()["issue"][0]["expression"] == ["parameters"]
    assert repeated.status_code == 400
    assert repeated.json()["issue"][0]["expression"] == ["focus"]


async def test_the_latest_search_without_a_token_is_login(
    seeded: None, api_client: AsyncClient
) -> None:
    response = await api_client.get(LATEST_WEST)

    assert response.status_code == 401


async def test_the_search_writes_nothing(
    seeded: None, api_client: AsyncClient, neo4j_driver: AsyncDriver
) -> None:
    await api_client.get(LATEST_WEST, headers=lead())

    await nothing_written(neo4j_driver)


# GET /fhir/Observation/{id}: where Location points


async def test_the_location_of_a_created_report_reads_it_back(
    seeded: None, api_client: AsyncClient
) -> None:
    created = await post(api_client, report_body(4), west_reporter())

    response = await api_client.get(created.headers["location"], headers=west_reporter())

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == created.json()
    Observation.model_validate(response.json())


@pytest.mark.parametrize("role", SEARCH_ROLES)
async def test_the_board_roles_read_any_report(
    seeded_with_report: None, api_client: AsyncClient, role: Role
) -> None:
    response = await api_client.get(f"{OBSERVATION}/obs-west-1303", headers=bearer(role, ()))

    assert response.status_code == 200


async def test_a_report_of_another_service_and_an_unknown_report_are_the_same_404(
    seeded_with_report: None, api_client: AsyncClient
) -> None:
    other = await api_client.get(f"{OBSERVATION}/obs-west-1303", headers=ward_reporter())
    unknown = await api_client.get(f"{OBSERVATION}/obs-nowhere", headers=ward_reporter())
    malformed = await api_client.get(f"{OBSERVATION}/a%20b", headers=ward_reporter())
    wrong_role = await api_client.get(
        f"{OBSERVATION}/obs-west-1303", headers=bearer(Role.SUPPORT, ())
    )

    assert other.status_code == 404
    assert other.json() == unknown.json() == malformed.json() == wrong_role.json()


async def test_reading_a_report_without_a_token_is_login(
    seeded_with_report: None, api_client: AsyncClient
) -> None:
    response = await api_client.get(f"{OBSERVATION}/obs-west-1303")

    assert response.status_code == 401


# What the logs and bodies carry


async def test_no_response_body_holds_a_token_a_secret_or_a_patient_word(
    seeded: None, api_client: AsyncClient
) -> None:
    headers = west_reporter()
    created = await post(api_client, report_body(4), headers)
    refused = await post(api_client, report_body(4.5), headers, key="key-2")
    listing = await api_client.get(SERVICES, headers=headers)
    latest = await api_client.get(LATEST_WEST, headers=headers)

    for response in (created, refused, listing, latest):
        text = response.text.lower().replace("inpatient-beds", "")
        assert headers["Authorization"].split(" ")[1] not in response.text
        assert TEST_BFF_SECRET.decode() not in response.text
        assert "postcode" not in text
        assert "patient" not in text.replace("{patient}", "")


async def test_a_report_stored_but_not_readable_back_is_a_500_with_no_detail(
    seeded: None, api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def nothing(self: Neo4jCapacityRepository, report_id: str) -> None:
        return None

    monkeypatch.setattr(Neo4jCapacityRepository, "get", nothing)

    response = await post(api_client, report_body(4), west_reporter())

    assert response.status_code == 500
    assert response.json()["issue"][0]["code"] == "exception"
    assert response.json()["issue"][0]["diagnostics"] == "Internal error"
