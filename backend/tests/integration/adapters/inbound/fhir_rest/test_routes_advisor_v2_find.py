"""POST /advisor-v2/find against real Neo4j (DEC-1379): the found services with their position and
the area they cover, and every other service of the tenant as not suitable with its reasons.
Tenant B, with a token of its own, never sees tenant A's services. The audit entry holds service
ids, status, figure state and criteria version only. Sample values only: no patient data.
"""

import json
from datetime import date, time
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient
from neo4j import AsyncDriver, AsyncManagedTransaction

from overwatch.adapters.inbound.fhir_rest.auth import BFF_SECRET_NAME
from overwatch.adapters.testing.fixed_secrets import FixedSecretStore
from overwatch.adapters.testing.memory_cache import InMemoryCache
from overwatch.adapters.testing.tokens import TEST_BFF_SECRET
from overwatch.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from overwatch.bootstrap.container import Container
from overwatch.domain.codes import (
    Cadence,
    Channel,
    CriteriaStatus,
    Measure,
    NeedCategory,
    Role,
    ServiceCategory,
)
from overwatch.domain.model.criteria import ServiceCriteria
from overwatch.domain.model.flags import SERVICE_FLAG_SUSPENDED, ServiceFlag
from overwatch.domain.model.service import AvailableTime, ServiceProfile
from tests.support.api import R01_TEST_NOW, token_headers
from tests.support.neo4j import write_tx
from tests.support.uow import ensure_audit_heads

pytestmark = pytest.mark.asyncio(loop_scope="session")

POSTCODE = "DT4 8XX"
BODY = {"postcode": POSTCODE, "ageBand": "80+", "needs": ["frailty"], "urgency": "today"}
JSON = {"Content-Type": "application/json"}
ASKERS = {
    Role.LEAD: "prac-lead",
    Role.ADVISOR: "prac-advisor",
    Role.ADVISOR_V2: "advisor-v2-1",
    Role.CLINICAL: "prac-clinical",
}
NOT_ASKERS = (Role.REPORTER, Role.WALL, Role.OWNER, Role.EXEC, Role.ANALYTICS_USER)


def _ask_service(role: Role) -> str:
    return f"svc-ask-{role.value}"


def _profile(service_id: str) -> ServiceProfile:
    return ServiceProfile(
        id=service_id,
        name=f"Service {service_id}",
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


def _criteria(service_id: str, districts: frozenset[str]) -> ServiceCriteria:
    return ServiceCriteria(
        id=f"crit-{service_id}",
        service_id=service_id,
        version=2,
        status=CriteriaStatus.CURRENT,
        age_min=18,
        age_max=None,
        districts=districts,
        accepts=frozenset({NeedCategory.FRAILTY}),
        excludes=frozenset(),
        review_by=date(2027, 1, 15),
        owner_role_id="role-owner",
    )


@pytest_asyncio.fixture(loop_scope="session")
async def find_world(
    api_app: FastAPI,
    test_container: Container,
    uow_factory_a: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    api_app.state.secrets = FixedSecretStore({BFF_SECRET_NAME: TEST_BFF_SECRET})
    api_app.state.cache = InMemoryCache(test_container.clock)
    await ensure_audit_heads(neo4j_driver, tenant_id)
    async with uow_factory_a() as uow:
        for service_id, districts in (
            ("svc-fits", frozenset({"DT4"})),
            ("svc-elsewhere", frozenset({"DT9"})),
            ("svc-suspended", frozenset({"DT4"})),
        ):
            await uow.services.save(_profile(service_id))
            await uow.criteria.add(_criteria(service_id, districts))
        await uow.services.save(_profile("svc-no-criteria"))
        await uow.flags.set_service_flag(
            ServiceFlag(
                "svc-suspended",
                SERVICE_FLAG_SUSPENDED,
                True,
                "closed-unexpectedly",
                "prac-lead",
                R01_TEST_NOW,
                expired_count=0,
            )
        )
        await uow.commit()

    async def cover(tx: AsyncManagedTransaction) -> None:
        for order, district in enumerate(("DT2", "DT1")):
            await tx.run(
                "MATCH (s:HealthcareService {id: 'svc-fits', tenantId: $tenant}) "
                "MERGE (a:Resource:Location {key: $key, id: $id, tenantId: $tenant}) "
                "SET a.name = $name "
                "MERGE (s)-[r:COVERAGE_AREA {fhirPath: 'HealthcareService.coverageArea'}]->(a) "
                "SET r.order = $order",
                tenant=tenant_id,
                key=f"Location/area-svc-fits-{district}",
                id=f"area-svc-fits-{district}",
                name=district,
                order=order,
            )

    await write_tx(neo4j_driver, cover)


async def _find(api_client: AsyncClient, tenant: str) -> dict[str, Any]:
    response = await api_client.post(
        "/advisor-v2/find",
        json=BODY,
        headers=token_headers(tenant, Role.ADVISOR_V2, sub="advisor-v2-1"),
    )
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert POSTCODE not in response.text
    return response.json()  # type: ignore[no-any-return]


async def test_find_returns_the_found_service_with_position_and_coverage_and_the_rest_with_reasons(
    api_client: AsyncClient, find_world: None, tenant_id: str
) -> None:
    body = await _find(api_client, tenant_id)

    assert [s["serviceId"] for s in body["services"]] == ["svc-fits"]
    (fits,) = body["services"]
    assert {"position", "coverage"} <= set(fits)
    assert fits["position"] is None  # no Location was recorded for the site
    assert set(fits["coverage"]) == {"districts", "circle"}
    assert fits["coverage"]["districts"] == ["DT1", "DT2"]
    circle = fits["coverage"]["circle"]
    assert circle is None or set(circle) == {"lat", "lon", "radiusMeters"}
    by_id = {n["serviceId"]: n for n in body["notSuitable"]}
    assert set(by_id) == {"svc-elsewhere", "svc-suspended", "svc-no-criteria"}
    assert set(by_id["svc-elsewhere"]) == {
        "serviceId",
        "name",
        "category",
        "status",
        "reasons",
        "position",
    }
    assert any(r.startswith("Does not cover") for r in by_id["svc-elsewhere"]["reasons"])
    assert by_id["svc-suspended"]["reasons"] == ["Not currently taking referrals"]
    assert by_id["svc-no-criteria"]["reasons"] == ["No current criteria"]
    names = [(n["name"], n["serviceId"]) for n in body["notSuitable"]]
    assert names == sorted(names)
    assert "groupTotals" in body


async def test_found_and_not_suitable_together_are_the_tenants_board(
    api_client: AsyncClient, find_world: None, tenant_id: str
) -> None:
    body = await _find(api_client, tenant_id)

    found = {s["serviceId"] for s in body["services"]}
    refused = {n["serviceId"] for n in body["notSuitable"]}
    assert found.isdisjoint(refused)
    assert found | refused == {"svc-fits", "svc-elsewhere", "svc-suspended", "svc-no-criteria"}


async def test_another_tenant_never_sees_these_services(
    api_client: AsyncClient, find_world: None, other_tenant_id: str
) -> None:
    body = await _find(api_client, other_tenant_id)

    assert body["services"] == []
    assert body["notSuitable"] == []


async def test_the_find_audit_entry_holds_no_reason_district_or_position(
    api_client: AsyncClient, find_world: None, tenant_id: str, uow_factory_a: UnitOfWorkFactory
) -> None:
    await _find(api_client, tenant_id)

    async with uow_factory_a() as uow:
        records = await uow.audit.records_for("svc-fits")
    entries = [r.entry for r in records if r.entry.use_case == "FindServices"]
    assert entries
    for entry in entries:
        assert set(entry.snapshot) == {"services"}
        for row in entry.snapshot["services"]:
            assert set(row) == {"id", "status", "figure_unavailable", "criteria_version", "order"}
        text = json.dumps(entry.snapshot).lower()
        for value in (
            POSTCODE,
            "dt48xx",
            "dt4",
            "dt2",
            "80+",
            "frailty",
            "today",
            "does not cover",
        ):
            assert value.lower() not in text, value
