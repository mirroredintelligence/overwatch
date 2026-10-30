"""The advisor's read of a service's criteria (W7A-A7, DEC-771) against real Neo4j.

The criteria dialog on the options list shows what a service accepts and what it does not. An
advisor reads the current version only: a change waiting for approval and the superseded versions
are the owner's and the leads' to see. Every version answers its accepts, excludes and age range.
The second tenant's advisor sees no history for the same service id. Sample values only.
"""

import pytest
from httpx import AsyncClient

from diucs.domain.codes import Role
from tests.integration.adapters.inbound.fhir_rest.test_routes_criteria import (
    OWNER,
    SERVICE,
    _change,
    criteria_world,
    test_container,
)
from tests.support.api import token_headers

__all__ = ["criteria_world", "test_container"]

pytestmark = pytest.mark.asyncio(loop_scope="session")

SUBJECT = {"subject": f"HealthcareService/{SERVICE}"}


async def _submit_a_change(client: AsyncClient, tenant_id: str, key: str) -> None:
    response = await client.post(
        "/fhir/Basic",
        json=_change(),
        headers={"Idempotency-Key": key, **token_headers(tenant_id, Role.OWNER, sub=OWNER)},
    )
    assert response.status_code == 201, response.text


async def test_an_advisor_reads_the_current_version_with_what_it_accepts_and_excludes(
    api_client: AsyncClient, criteria_world: None, tenant_id: str
) -> None:
    response = await api_client.get(
        "/fhir/Basic",
        params=SUBJECT,
        headers=token_headers(tenant_id, Role.ADVISOR, sub="prac-advisor"),
    )

    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1
    version = response.json()["entry"][0]["resource"]
    assert version["meta"]["versionId"] == "1"
    assert version["status"] == "current"
    assert version["accepts"] == ["frailty"]
    assert version["excludes"] == []
    assert version["ageMin"] == 18
    assert "ageMax" not in version
    assert version["reviewBy"] == "2026-12-12"
    assert "changeReason" not in version


async def test_an_advisor_never_sees_a_change_waiting_for_approval(
    api_client: AsyncClient, criteria_world: None, tenant_id: str
) -> None:
    await _submit_a_change(api_client, tenant_id, "criteria-advisor-0001")

    advisor = await api_client.get(
        "/fhir/Basic",
        params=SUBJECT,
        headers=token_headers(tenant_id, Role.ADVISOR, sub="prac-advisor"),
    )
    owner = await api_client.get(
        "/fhir/Basic", params=SUBJECT, headers=token_headers(tenant_id, Role.OWNER, sub=OWNER)
    )

    assert [entry["resource"]["meta"]["versionId"] for entry in advisor.json()["entry"]] == ["1"]
    assert [entry["resource"]["meta"]["versionId"] for entry in owner.json()["entry"]] == [
        "2",
        "1",
    ]


async def test_the_owner_and_the_clinical_advisor_read_the_accepts_and_excludes_too(
    api_client: AsyncClient, criteria_world: None, tenant_id: str
) -> None:
    for role in (Role.OWNER, Role.CLINICAL, Role.LEAD):
        response = await api_client.get(
            "/fhir/Basic", params=SUBJECT, headers=token_headers(tenant_id, role, sub=OWNER)
        )

        version = response.json()["entry"][0]["resource"]
        assert version["accepts"] == ["frailty"], role
        assert version["excludes"] == [], role


async def test_tenant_bs_advisor_sees_no_criteria_for_the_same_service_id(
    api_client: AsyncClient, criteria_world: None, other_tenant_id: str
) -> None:
    response = await api_client.get(
        "/fhir/Basic",
        params=SUBJECT,
        headers=token_headers(other_tenant_id, Role.ADVISOR, sub="prac-advisor-b"),
    )

    assert response.status_code == 200, response.text
    assert response.json()["total"] == 0
    assert response.json().get("entry", []) == []
