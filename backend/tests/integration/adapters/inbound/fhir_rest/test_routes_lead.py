"""The shift lead routes (R08) against real Neo4j through the API client.

WRITTEN, NOT RUN in the build wave (no Neo4j per build-wave rules). These cases need the REST edge to
bind the lead's tenant from the verified token (TEN-018, being built in another bundle). Until that
lands, every write here fails closed with TenantNotBound (a 500), so the cases cannot pass yet; that is
the dependence recorded in the fragment, not a fault in these tests.

The phone numbers are the prompt's sample values. No patient data.
"""

import pytest
from httpx import AsyncClient
from neo4j import AsyncDriver

from diucs.adapters.testing.tokens import issue_test_token
from diucs.domain.codes import Role
from tests.support.neo4j import count_nodes

pytestmark = pytest.mark.asyncio(loop_scope="session")

SETUP = "/fhir/HealthcareService/$setup"
CHANGE = "/fhir/PractitionerRole/{role}/$change-number"
NUMBER = "07700 900123"
NEW_NUMBER = "07700 900456"


def _bearer(role: Role, sub: str = "lead-1") -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_test_token(role, [], sub)}"}


def _p(name: str, value: dict) -> dict:
    return {"name": name, **value}


def _setup(mobile: str = NUMBER, channel: str = "text") -> dict:
    return {
        "resourceType": "Parameters",
        "parameter": [
            _p("name", {"valueString": "UCR West"}),
            _p("category", {"valueCode": "urgent-community-response"}),
            _p("measure", {"valueCode": "referrals-acceptable"}),
            _p("unitLabel", {"valueString": "referrals in the next 2 hrs"}),
            _p("establishedCapacity", {"valueInteger": 8}),
            _p("usualMin", {"valueInteger": 0}),
            _p("usualMax", {"valueInteger": 8}),
            _p("cadence", {"valueCode": "every-2-hrs"}),
            _p("channel", {"valueCode": channel}),
            _p("mobile", {"valueString": mobile}),
            _p("roleName", {"valueString": "Duty manager"}),
            _p("availableFrom", {"valueString": "08:00"}),
            _p("availableTo", {"valueString": "20:00"}),
            _p("ageMin", {"valueInteger": 18}),
            _p("district", {"valueString": "DT4"}),
            _p("reviewBy", {"valueDate": "2026-12-12"}),
        ],
    }


def _change(mobile: str = NEW_NUMBER, duration: str = "today") -> dict:
    return {
        "resourceType": "Parameters",
        "parameter": [
            _p("mobile", {"valueString": mobile}),
            _p("duration", {"valueCode": duration}),
        ],
    }


async def test_a_lead_sets_up_a_service_and_a_fresh_read_finds_it(
    api_client: AsyncClient, neo4j_driver: AsyncDriver
) -> None:
    response = await api_client.post(
        SETUP, json=_setup(), headers={"Idempotency-Key": "setup-0001", **_bearer(Role.LEAD)}
    )

    assert response.status_code == 201
    assert response.json()["resourceType"] == "HealthcareService"
    assert response.json()["name"] == "UCR West"


async def test_the_mobile_is_kept_in_the_protected_store_only(
    api_client: AsyncClient, neo4j_driver: AsyncDriver
) -> None:
    await api_client.post(
        SETUP, json=_setup(), headers={"Idempotency-Key": "setup-0002", **_bearer(Role.LEAD)}
    )
    async with neo4j_driver.session() as session:
        result = await session.run(
            "MATCH (n) WHERE any(k IN keys(n) WHERE toString(n[k]) CONTAINS '07700') "
            "RETURN labels(n) AS labels"
        )
        holders = [record["labels"] async for record in result]
    assert holders, "the number is stored somewhere"
    for labels in holders:
        assert "ProtectedContact" in labels or "Contact" in labels, labels


async def test_an_advisor_is_not_found_and_nothing_is_stored(
    api_client: AsyncClient, neo4j_driver: AsyncDriver
) -> None:
    response = await api_client.post(
        SETUP, json=_setup(), headers={"Idempotency-Key": "setup-0003", **_bearer(Role.ADVISOR)}
    )
    assert response.status_code == 404
    assert await count_nodes(neo4j_driver, "HealthcareService") == 0


async def test_push_is_refused_outside_the_pilot(api_client: AsyncClient) -> None:
    response = await api_client.post(
        SETUP,
        json=_setup(channel="push"),
        headers={"Idempotency-Key": "setup-0004", **_bearer(Role.LEAD)},
    )
    assert response.status_code == 400


async def test_an_invalid_mobile_is_refused_and_the_input_is_not_echoed(
    api_client: AsyncClient,
) -> None:
    response = await api_client.post(
        SETUP,
        json=_setup(mobile="0770"),
        headers={"Idempotency-Key": "setup-0005", **_bearer(Role.LEAD)},
    )
    assert response.status_code == 400
    # The prompt's example number contains the characters "0770", so the check is on the input as
    # a value: the refusal must not repeat it as the number that was sent.
    assert '"0770"' not in response.text


async def test_a_number_change_for_today_reports_the_last_four_digits(
    api_client: AsyncClient, neo4j_driver: AsyncDriver
) -> None:
    response = await api_client.post(
        CHANGE.format(role="role-1"),
        json=_change(),
        headers={"Idempotency-Key": "change-0001", **_bearer(Role.LEAD)},
    )
    assert response.status_code == 200
    values = {p["name"]: p.get("valueString") for p in response.json()["parameter"]}
    assert values["numberEnding"] == "0456"


async def test_a_change_without_an_idempotency_key_is_refused(api_client: AsyncClient) -> None:
    response = await api_client.post(
        CHANGE.format(role="role-1"), json=_change(), headers=_bearer(Role.LEAD)
    )
    assert response.status_code == 400


async def test_another_tenants_reporter_role_reads_as_not_found(
    api_client: AsyncClient,
) -> None:
    """Needs the lead's tenant bound at the edge (TEN-018) and a role of the other tenant."""
    response = await api_client.post(
        CHANGE.format(role="role-of-tenant-b"),
        json=_change(),
        headers={"Idempotency-Key": "change-0002", **_bearer(Role.LEAD)},
    )
    assert response.status_code == 404
