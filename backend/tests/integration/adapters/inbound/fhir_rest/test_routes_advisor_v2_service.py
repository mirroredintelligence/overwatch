"""The Advisor v2 single-service routes (DEC-1377) against real Neo4j: the check of one patient
against one service, and the ask for a service's capacity.

Tenant A holds a service that takes the patient, one that does not cover the postcode, a suspended
one, one with no criteria, and one service for each role that may ask. Tenant B, with a token of its
own, reads and asks none of A's: every id is the 404 of a record that is not there. The audit entry
of a check holds the service id and the result only. Sample values only: no patient data.
"""

import json
from datetime import date, time
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient
from neo4j import AsyncDriver

from overwatch.adapters.inbound.fhir_rest.auth import BFF_SECRET_NAME
from overwatch.adapters.testing.fixed_secrets import FixedSecretStore
from overwatch.adapters.testing.memory_cache import InMemoryCache
from overwatch.adapters.testing.tokens import TEST_BFF_SECRET
from overwatch.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from overwatch.application.use_cases.ask_capacity_now import ASK_ROLES
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
async def v2_world(
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
    await ensure_audit_heads(neo4j_driver, other_tenant_id)
    async with uow_factory_a() as uow:
        for service_id, districts in (
            ("svc-fits", frozenset({"DT4"})),
            ("svc-elsewhere", frozenset({"DT9"})),
            ("svc-suspended", frozenset({"DT4"})),
        ):
            await uow.services.save(_profile(service_id))
            await uow.criteria.add(_criteria(service_id, districts))
        await uow.services.save(_profile("svc-no-criteria"))
        for role in ASKERS:
            await uow.services.save(_profile(_ask_service(role)))
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


def _check(service: str) -> str:
    return f"/advisor-v2/services/{service}/check"


def _ask(service: str) -> str:
    return f"/advisor-v2/services/{service}/ask"


async def test_a_service_that_takes_the_patient_fits(
    api_client: AsyncClient, v2_world: None, tenant_id: str
) -> None:
    response = await api_client.post(
        _check("svc-fits"),
        json=BODY,
        headers=token_headers(tenant_id, Role.ADVISOR_V2, sub="advisor-v2-1"),
    )

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert set(body) == {
        "serviceId",
        "fits",
        "reasons",
        "fitsNeeds",
        "warnings",
        "phone",
        "status",
        "figureUnavailable",
    }
    assert (body["serviceId"], body["fits"], body["reasons"]) == ("svc-fits", True, [])
    assert any("frailty" in line for line in body["fitsNeeds"])
    assert body["phone"] is None
    assert body["figureUnavailable"] is True  # no figure was ever reported
    assert POSTCODE not in response.text


async def test_the_advisor_may_check_too_and_a_service_outside_its_area_does_not_fit(
    api_client: AsyncClient, v2_world: None, tenant_id: str
) -> None:
    response = await api_client.post(
        _check("svc-elsewhere"),
        json=BODY,
        headers=token_headers(tenant_id, Role.ADVISOR, sub="prac-advisor"),
    )

    body = response.json()
    assert response.status_code == 200, response.text
    assert body["fits"] is False
    assert body["fitsNeeds"] == []
    assert any(reason.startswith("Does not cover") for reason in body["reasons"])
    assert body["warnings"] == []  # none for a never-reported service (unit test covers more)


async def test_a_suspended_service_and_one_with_no_criteria_never_fit(
    api_client: AsyncClient, v2_world: None, tenant_id: str
) -> None:
    headers = token_headers(tenant_id, Role.ADVISOR_V2, sub="advisor-v2-1")
    suspended = await api_client.post(_check("svc-suspended"), json=BODY, headers=headers)
    none = await api_client.post(_check("svc-no-criteria"), json=BODY, headers=headers)

    assert suspended.json()["fits"] is False
    assert suspended.json()["reasons"] == ["Not currently taking referrals"]
    assert none.json()["fits"] is False
    assert none.json()["reasons"] == ["No current criteria"]


async def test_the_check_audit_entry_holds_the_service_and_the_result_only(
    api_client: AsyncClient, v2_world: None, tenant_id: str, uow_factory_a: UnitOfWorkFactory
) -> None:
    await api_client.post(
        _check("svc-fits"),
        json=BODY,
        headers=token_headers(tenant_id, Role.ADVISOR_V2, sub="advisor-v2-1"),
    )

    async with uow_factory_a() as uow:
        records = await uow.audit.records_for("svc-fits")
    entries = [r.entry for r in records if r.entry.use_case == "CheckServiceFit"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry.snapshot == {"service_id": "svc-fits", "fits": True, "criteria_version": 2}
    assert entry.actor.practitioner_id == "advisor-v2-1"
    text = (json.dumps(entry.snapshot) + "|".join(entry.entity_ids)).lower()
    for value in (POSTCODE, "dt48xx", "dt4", "80+", "frailty", "today"):
        assert value.lower() not in text, value


@pytest.mark.parametrize("role", NOT_ASKERS + (Role.PLATFORM_OPERATOR,))
async def test_other_roles_cannot_check(
    role: Role, api_client: AsyncClient, v2_world: None, tenant_id: str
) -> None:
    response = await api_client.post(
        _check("svc-fits"), json=BODY, headers=token_headers(tenant_id, role, sub="someone-1")
    )
    assert response.status_code in (401, 404)


async def test_another_tenants_service_is_not_found_for_the_check_and_the_ask(
    api_client: AsyncClient, v2_world: None, other_tenant_id: str
) -> None:
    other = token_headers(other_tenant_id, Role.ADVISOR_V2, sub="advisor-v2-1")
    other_lead = token_headers(other_tenant_id, Role.LEAD, sub="prac-lead")

    check = await api_client.post(_check("svc-fits"), json=BODY, headers=other)
    ask = await api_client.post(
        _ask("svc-ask-lead"), headers={**JSON, "Idempotency-Key": "v2-ask-other-0001", **other}
    )
    lead_ask = await api_client.post(
        _ask("svc-ask-lead"),
        headers={**JSON, "Idempotency-Key": "v2-ask-other-0002", **other_lead},
    )

    assert (check.status_code, ask.status_code, lead_ask.status_code) == (404, 404, 404)


@pytest.mark.parametrize("role", list(ASK_ROLES))
async def test_the_four_roles_may_ask_and_it_is_audited_with_the_actor(
    role: Role,
    api_client: AsyncClient,
    v2_world: None,
    tenant_id: str,
    uow_factory_a: UnitOfWorkFactory,
) -> None:
    service = _ask_service(role)
    response = await api_client.post(
        _ask(service),
        headers={
            **JSON,
            "Idempotency-Key": f"v2-ask-{role.value}-0001",
            **token_headers(tenant_id, role, sub=ASKERS[role]),
        },
    )

    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    assert body == {"queued": True, "dueAt": "2026-10-23T13:12:00Z"}
    async with uow_factory_a() as uow:
        records = await uow.audit.records_for(service)
    (entry,) = [r.entry for r in records if r.entry.use_case == "AskCapacityNow"]
    assert (entry.actor.role, entry.actor.practitioner_id) == (role, ASKERS[role])


@pytest.mark.parametrize("role", NOT_ASKERS)
async def test_the_other_roles_cannot_ask(
    role: Role, api_client: AsyncClient, v2_world: None, tenant_id: str
) -> None:
    response = await api_client.post(
        _ask("svc-fits"),
        headers={
            **JSON,
            "Idempotency-Key": f"v2-ask-refused-{role.value}",
            **token_headers(tenant_id, role, sub="someone-1"),
        },
    )
    assert response.status_code == 404


async def test_a_second_ask_when_one_is_due_is_a_409_and_the_same_key_replays(
    api_client: AsyncClient, v2_world: None, tenant_id: str
) -> None:
    advisor = token_headers(tenant_id, Role.ADVISOR, sub="prac-advisor")
    service = _ask_service(Role.ADVISOR)
    first = await api_client.post(
        _ask(service), headers={**JSON, "Idempotency-Key": "v2-ask-replay-0001", **advisor}
    )
    replay = await api_client.post(
        _ask(service), headers={**JSON, "Idempotency-Key": "v2-ask-replay-0001", **advisor}
    )
    second = await api_client.post(
        _ask(service), headers={**JSON, "Idempotency-Key": "v2-ask-replay-0002", **advisor}
    )

    assert first.status_code == 200, first.text
    assert (replay.status_code, replay.json()) == (200, first.json())
    assert second.status_code == 409
