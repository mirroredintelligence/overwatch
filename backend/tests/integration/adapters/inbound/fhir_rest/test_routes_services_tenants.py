"""Two-tenant tests for the service and report endpoints (R04, DEC-130 to DEC-132, DEC-142).

Tenant A is the run tenant that the harness binds for the test. Tenant B is seeded through its own
units of work (`uow_factory_b`) and its requests carry a token that names tenant B (`_b_lead`): the
REST edge binds the tenant from the verified token (TEN-018), so `as_tenant` around a request only
restores the test's own binding afterwards. The routes never read a tenant: it comes only from the
unit of work.

Until TEN-032 drops the single-property keys, two tenants cannot share a resource id or a concept
on the shared test schema, so B's ids, category, measure and source differ from A's. Since TEN-009
the resource store scopes its reads, so tenant A's lookups never find tenant B's service or
reports: each of those reads as the same 404 as an unknown id. The capacity and flag statements the
use case runs are still unconverted (tenant-pending, evidence R04), but every one of them is reached
only after a scoped service lookup. The same id in both tenants is not tested here (it needs a
contracted container).
"""

import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from neo4j import AsyncDriver

from diucs.adapters.inbound.fhir_rest.app import create_app
from diucs.adapters.inbound.fhir_rest.auth import BFF_SECRET_NAME
from diucs.adapters.outbound.audit_neo4j.audit_log import ensure_audit_head
from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.outbound.graph_store.migrations import apply_migrations
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.adapters.testing.tokens import TEST_BFF_SECRET
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.bootstrap.container import Container, build_for_tests
from diucs.domain.codes import Measure, ReportSource, ReportType, Role, ServiceCategory
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.service import ServiceProfile
from tests.integration.adapters.inbound.fhir_rest.test_routes_services import (
    LATEST_WEST,
    OBSERVATION,
    SERVICES,
    WEST_PRIOR,
    fields,
    ids,
    lead,
    post,
    report_body,
    services_app,
    west_reporter,
)
from tests.integration.application.test_query_board import WEST
from tests.support.api import R01_TEST_NOW, seed_edge_tenants, token_headers
from tests.support.neo4j import count_nodes, throwaway_driver
from tests.support.tenancy import as_tenant
from tests.support.tenant_seed import contract_schema
from tests.support.uow import tenant_uow_factory

__all__ = ["services_app"]

pytestmark = pytest.mark.asyncio(loop_scope="session")

B_SERVICE = "svc-b-clinic"
B_REPORT = "obs-b-1303"
# B uses another category, measure and source than A: the shared test schema keeps the old
# single-property keys of Concept nodes until TEN-032, so two tenants cannot hold the same concept
# there (lesson L164 item 5).
B_PROFILE = ServiceProfile(
    **{
        **fields(WEST),
        "id": B_SERVICE,
        "name": "Clinic B",
        "category": ServiceCategory.SAME_DAY_EMERGENCY_CARE,
        "measure": Measure.FREE_SLOTS,
        "unit_label": "slots",
    }
)
B_PRIOR = CapacityReport(
    id=B_REPORT,
    service_id=B_SERVICE,
    value=7,
    measure=Measure.FREE_SLOTS,
    effective_at=datetime(2026, 10, 23, 13, 3, tzinfo=UTC),
    source=ReportSource.EMAIL,
    report_type=ReportType.NUMBER,
)
B_LATEST = f"{OBSERVATION}?focus=HealthcareService/{B_SERVICE}&_sort=-date&_count=1"


@pytest_asyncio.fixture(loop_scope="session")
async def both_tenants(
    services_app: FastAPI,
    test_container: Container,
    uow_factory_b: UnitOfWorkFactory,
) -> None:
    """A holds UCR West with one report. B holds Clinic B with one report."""
    async with test_container.uow_factory() as uow:
        await uow.services.save(WEST)
        await uow.capacity.add(WEST_PRIOR)
        await uow.commit()
    async with uow_factory_b() as uow:
        await uow.services.save(B_PROFILE)
        await uow.capacity.add(B_PRIOR)
        await uow.commit()


def _b_lead() -> dict[str, str]:
    """Tenant B's lead: a token that names tenant B, which is what the REST edge binds (TEN-018)."""
    return token_headers(os.environ["DIUCS_TEST_OTHER_TENANT"], Role.LEAD, (), "prac-lead-b")


async def test_tenant_a_lists_only_its_own_services(
    both_tenants: None, api_client: AsyncClient
) -> None:
    response = await api_client.get(SERVICES, headers=lead())

    assert ids(response.json()) == ["svc-ucr-west"]
    assert response.json()["total"] == 1


async def test_tenant_bs_service_id_is_the_same_404_as_an_unknown_id(
    both_tenants: None, api_client: AsyncClient
) -> None:
    unknown = await api_client.get(f"{SERVICES}/svc-nowhere", headers=lead())
    response = await api_client.get(f"{SERVICES}/{B_SERVICE}", headers=lead())

    assert response.status_code == 404
    assert response.json() == unknown.json()


async def test_tenant_bs_service_in_a_focus_search_is_the_same_404_as_an_unknown_id(
    both_tenants: None, api_client: AsyncClient
) -> None:
    unknown = await api_client.get(
        f"{OBSERVATION}?focus=HealthcareService/svc-nowhere", headers=lead()
    )
    response = await api_client.get(B_LATEST, headers=lead())

    assert response.status_code == 404
    assert response.json() == unknown.json()


async def test_tenant_bs_report_id_is_the_same_404_as_an_unknown_id(
    both_tenants: None, api_client: AsyncClient
) -> None:
    unknown = await api_client.get(f"{OBSERVATION}/obs-nowhere", headers=lead())
    response = await api_client.get(f"{OBSERVATION}/{B_REPORT}", headers=lead())

    assert response.status_code == 404
    assert response.json() == unknown.json()


async def test_a_report_for_tenant_bs_service_is_the_same_404_and_changes_nothing_of_bs(
    both_tenants: None,
    api_client: AsyncClient,
    uow_factory_b: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
) -> None:
    unknown = await post(
        api_client, report_body(4, service="svc-nowhere", method="advisor-phoned"), lead(), "key-0"
    )
    response = await post(
        api_client, report_body(4, service=B_SERVICE, method="advisor-phoned"), lead()
    )

    assert response.status_code == 404
    assert response.json() == unknown.json()
    async with uow_factory_b() as uow:
        latest = await uow.capacity.latest(B_SERVICE)
    assert latest == B_PRIOR
    assert await count_nodes(neo4j_driver, "Observation") == 2  # A's and B's prior reports only


async def test_tenant_as_service_is_not_found_for_tenant_b(
    both_tenants: None, api_client: AsyncClient, other_tenant_id: str
) -> None:
    unknown = await api_client.get(f"{SERVICES}/svc-nowhere", headers=_b_lead())
    with as_tenant(other_tenant_id):
        service = await api_client.get(f"{SERVICES}/svc-ucr-west", headers=_b_lead())
        latest = await api_client.get(LATEST_WEST, headers=_b_lead())
        listing = await api_client.get(SERVICES, headers=_b_lead())

    assert service.status_code == 404
    assert service.json() == unknown.json()
    assert latest.status_code == 404
    assert latest.json() == unknown.json()
    assert ids(listing.json()) == [B_SERVICE]


async def test_a_report_by_tenant_a_changes_nothing_of_tenant_b(
    both_tenants: None,
    api_client: AsyncClient,
    uow_factory_b: UnitOfWorkFactory,
    test_container: Container,
) -> None:
    response = await post(api_client, report_body(2, at="2026-10-23T10:00:00Z"), west_reporter())

    assert response.status_code == 201
    async with uow_factory_b() as uow:
        assert await uow.capacity.latest(B_SERVICE) == B_PRIOR
        profile = await uow.services.get(B_SERVICE)
    assert profile == B_PROFILE
    async with test_container.uow_factory() as uow:
        stored = await uow.capacity.get(response.json()["id"])
    assert stored is not None
    assert stored.service_id == "svc-ucr-west"


@asynccontextmanager
async def _b_on_its_own_chain(tenant: str) -> AsyncIterator[AsyncClient]:
    """A private Neo4j on the schema of TEN-032, with tenant B's service and its own audit chain
    head, and a client for an app on it. The shared harness schema keeps one AuditHead key on the
    id alone until TEN-032, so a second tenant cannot write there (the audit head, TEN-017)."""
    async with throwaway_driver() as (container, driver):
        await apply_migrations(driver)
        await contract_schema(driver)
        connection = Neo4jConnection(container.uri, container.user, container.password)
        await connection.open()
        try:
            clock = FixedClock(R01_TEST_NOW)
            app = create_app(build_for_tests(clock=clock, neo4j=connection))
            app.state.secrets = FixedSecretStore({BFF_SECRET_NAME: TEST_BFF_SECRET})
            app.state.cache = InMemoryCache(clock)
            factory = tenant_uow_factory(driver, tenant, clock)
            with as_tenant(tenant):
                await ensure_audit_head(driver)
            await seed_edge_tenants(driver, tenant)
            async with factory() as uow:
                await uow.services.save(B_PROFILE)
                await uow.capacity.add(B_PRIOR)
                await uow.commit()
            async with AsyncClient(
                transport=ASGITransport(app=app, raise_app_exceptions=False),
                base_url="http://test",
            ) as client:
                yield client
        finally:
            await connection.close()


async def test_tenant_b_reads_and_reports_for_its_own_service(
    other_tenant_id: str, tenant_id: str
) -> None:
    async with _b_on_its_own_chain(other_tenant_id) as client:
        with as_tenant(other_tenant_id):
            service = await client.get(f"{SERVICES}/{B_SERVICE}", headers=_b_lead())
            created = await post(
                client,
                report_body(
                    5,
                    service=B_SERVICE,
                    at="2026-10-23T13:10:00Z",
                    method="advisor-phoned",
                    measure="free-slots",
                    unit="{slot}",
                ),
                _b_lead(),
                key="b-key-1",
            )
            latest = await client.get(B_LATEST, headers=_b_lead())

    assert service.status_code == 200
    assert created.status_code == 201
    assert latest.status_code == 200
    assert latest.json()["entry"][0]["resource"]["id"] == created.json()["id"]
    for response in (service, created, latest):
        assert tenant_id not in response.text
        assert other_tenant_id not in response.text


async def test_a_tenant_in_the_body_a_header_or_the_query_is_never_read(
    both_tenants: None, api_client: AsyncClient, other_tenant_id: str, tenant_id: str
) -> None:
    claimed = {
        **report_body(4),
        "extension": [
            {
                "url": "https://diucs.example/StructureDefinition/tenantId",
                "valueString": other_tenant_id,
            }
        ],
    }
    in_body = await post(api_client, claimed, west_reporter())
    headers = {**lead(), "X-Tenant": other_tenant_id, "X-Tenant-Id": other_tenant_id}
    in_header = await api_client.get(f"{SERVICES}/svc-ucr-west", headers=headers)
    in_query = await api_client.get(
        SERVICES, params={"tenant": other_tenant_id, "_tenant": other_tenant_id}, headers=lead()
    )
    in_body_parameter = await post(
        api_client,
        json.dumps({**report_body(4), "tenantId": other_tenant_id}),
        west_reporter(),
        "k2",
    )

    assert in_body.status_code == 400
    assert in_body.json()["issue"][0]["expression"] == ["Observation"]
    assert in_header.status_code == 200
    assert in_header.json()["id"] == "svc-ucr-west"
    assert in_query.status_code == 400
    assert in_query.json()["issue"][0]["expression"] == ["parameters"]
    assert in_body_parameter.status_code == 400
    for response in (in_body, in_header, in_query, in_body_parameter):
        assert other_tenant_id not in response.text
        assert tenant_id not in response.text
