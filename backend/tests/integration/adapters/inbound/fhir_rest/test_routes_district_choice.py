"""Choosing a district when the postcode cannot be used (W50, W9H DEC-1045, DEC-1046), through the
API client against real Neo4j.

`$filter-options` offers the districts the tenant's services cover, as `district` parts, when the
postcode is not found or is out of area. The advisor picks one, and a PUT with the district
extension on the Patient keeps it as the case's district (the only way a district alone is kept: the
postcode field still takes a full postcode). Another tenant's districts are never offered, another
tenant's case is the one 404, and every role but an advisor and a clinical advisor is refused with
the 404 of a missing record (the platform operator is a 401 at the edge). Synthetic values only.
"""

import copy
import dataclasses
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from diucs.adapters.testing.fixed_geo import FixedPostcodeLocator
from diucs.application.ports.outbound.geo import LatLon
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.bootstrap.container import Container
from diucs.domain.codes import AgeBand, NeedCategory, ReferrerType, Role, Urgency
from diucs.domain.model.case import Case
from tests.integration.adapters.inbound.fhir_rest.test_routes_cases import (
    CASE_BODY,
    fresh_cases,
    route_state,
    seeded,
)
from tests.support.api import token_headers

__all__ = ["fresh_cases", "route_state", "seeded"]

pytestmark = pytest.mark.asyncio(loop_scope="session")

DISTRICT_EXTENSION = "https://diucs.example/StructureDefinition/postcode-district"
EDGE_REFUSED = {Role.PLATFORM_OPERATOR}
B_CASE_ID = "case-of-tenant-b-district"
PLACES = {
    "DT1": LatLon(lat=50.71, lon=-2.44),
    "DT2": LatLon(lat=50.72, lon=-2.46),
    "DT4": LatLon(lat=50.61, lon=-2.45),
    "DT9": LatLon(lat=50.9, lon=-2.1),
}


def headers(key: str, role: Role = Role.ADVISOR, **extra: str) -> dict[str, str]:
    return {**token_headers(role=role), "Idempotency-Key": key, **extra}


def district_body(district: str, **patient: Any) -> dict[str, Any]:
    return {
        "resourceType": "ServiceRequest",
        "contained": [
            {
                "resourceType": "Patient",
                "id": "p",
                "extension": [{"url": DISTRICT_EXTENSION, "valueCode": district}],
                **patient,
            }
        ],
    }


async def put(client: AsyncClient, case_id: str, body: dict[str, Any], key: str, role: Role) -> Any:
    return await client.put(
        f"/fhir/ServiceRequest/{case_id}",
        json=body,
        headers=headers(key, role, **{"If-Match": 'W/"1"'}),
    )


async def open_case(client: AsyncClient, key: str, postcode: str = "DT4 8XX") -> str:
    body = copy.deepcopy(CASE_BODY)
    body["contained"][0]["address"] = [{"postalCode": postcode}]
    response = await client.post("/fhir/ServiceRequest", json=body, headers=headers(key))
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def stored_district(container: Container, case_id: str) -> str | None:
    async with container.uow_factory() as uow:
        case = await uow.cases.get(case_id)
    return None if case is None else case.postcode


def with_places(api_app: FastAPI, places: dict[str, LatLon]) -> None:
    """The app answers from a locator that knows these districts (the container's knows none)."""
    container: Container = api_app.state.container
    api_app.state.container = dataclasses.replace(
        container, postcodes=FixedPostcodeLocator(postcodes={}, districts=places)
    )


def filter_body(case_id: str) -> dict[str, Any]:
    return {
        "resourceType": "Parameters",
        "parameter": [
            {"name": "case", "valueReference": {"reference": f"ServiceRequest/{case_id}"}}
        ],
    }


def district_parts(response: Any) -> list[str]:
    return [p["valueString"] for p in response.json()["parameter"] if p["name"] == "district"]


# ------------------------------------------------------------------------------- the offer


async def test_an_unknown_district_is_offered_the_covered_districts_the_locator_knows(
    api_client: AsyncClient, api_app: FastAPI, seeded: None
) -> None:
    case_id = await open_case(api_client, "dc-open-1", "ZZ9 9ZZ")
    with_places(api_app, {"DT3": PLACES["DT1"], "DT1": PLACES["DT2"], "DT9": PLACES["DT9"]})

    response = await api_client.post(
        "/fhir/HealthcareService/$filter-options",
        json=filter_body(case_id),
        headers=headers("dc-filter-1"),
    )

    assert response.status_code == 200, response.text
    names = [p["name"] for p in response.json()["parameter"]]
    assert "notFound" in names
    # DT9 is known to the locator but no service here covers it, so it is not a choice.
    assert district_parts(response) == ["DT1", "DT3"]


async def test_a_covered_known_district_is_offered_no_districts(
    api_client: AsyncClient, api_app: FastAPI, seeded: None
) -> None:
    case_id = await open_case(api_client, "dc-open-2")
    with_places(api_app, PLACES)

    response = await api_client.post(
        "/fhir/HealthcareService/$filter-options",
        json=filter_body(case_id),
        headers=headers("dc-filter-2"),
    )

    names = [p["name"] for p in response.json()["parameter"]]
    assert "notFound" not in names and "outOfArea" not in names
    assert district_parts(response) == []


async def test_an_out_of_area_district_is_offered_the_nearest_covered_districts_first(
    api_client: AsyncClient, api_app: FastAPI, seeded: None
) -> None:
    case_id = await open_case(api_client, "dc-open-3", "DT9 9AA")
    with_places(api_app, PLACES)

    response = await api_client.post(
        "/fhir/HealthcareService/$filter-options",
        json=filter_body(case_id),
        headers=headers("dc-filter-3"),
    )

    names = [p["name"] for p in response.json()["parameter"]]
    assert "outOfArea" in names
    assert district_parts(response) == ["DT1", "DT2", "DT4"]


async def test_the_answer_never_holds_the_cases_own_district_or_a_postcode(
    api_client: AsyncClient, api_app: FastAPI, seeded: None
) -> None:
    case_id = await open_case(api_client, "dc-open-4", "DT9 9AA")
    with_places(api_app, PLACES)

    response = await api_client.post(
        "/fhir/HealthcareService/$filter-options",
        json=filter_body(case_id),
        headers=headers("dc-filter-4"),
    )

    assert "DT9" not in district_parts(response)
    assert "9AA" not in response.text and "DT9 " not in response.text


# ------------------------------------------------------------------------------- the choice


async def test_a_chosen_district_becomes_the_cases_district_and_the_options_run_again(
    api_client: AsyncClient, api_app: FastAPI, test_container: Container, seeded: None
) -> None:
    case_id = await open_case(api_client, "dc-open-5", "ZZ9 9ZZ")
    with_places(api_app, PLACES)

    chosen = await put(api_client, case_id, district_body("dt1"), "dc-put-1", Role.ADVISOR)

    assert chosen.status_code == 200, chosen.text
    assert chosen.json()["contained"][0]["address"][0]["postalCode"] == "DT1"
    assert await stored_district(test_container, case_id) == "DT1"
    again = await api_client.post(
        "/fhir/HealthcareService/$filter-options",
        json=filter_body(case_id),
        headers=headers("dc-filter-5"),
    )
    names = [p["name"] for p in again.json()["parameter"]]
    assert "notFound" not in names and "outOfArea" not in names
    assert [p for p in again.json()["parameter"] if p["name"] == "option"]


@pytest.mark.parametrize("text", ["DT4 8XX", "DT48X9", "dt 4", "DT4,BH1"])
async def test_a_district_that_is_not_one_is_a_400_that_does_not_echo_it_and_changes_nothing(
    api_client: AsyncClient, test_container: Container, seeded: None, text: str
) -> None:
    case_id = await open_case(api_client, "dc-open-6")

    response = await put(api_client, case_id, district_body(text), "dc-put-2", Role.ADVISOR)

    assert response.status_code == 400
    assert text not in response.text
    assert await stored_district(test_container, case_id) == "DT4"


async def test_a_district_with_a_full_postcode_in_one_body_is_a_400_and_changes_nothing(
    api_client: AsyncClient, test_container: Container, seeded: None
) -> None:
    case_id = await open_case(api_client, "dc-open-7")
    body = district_body("BH1", address=[{"postalCode": "DT2 1AA"}])

    response = await put(api_client, case_id, body, "dc-put-3", Role.ADVISOR)

    assert response.status_code == 400
    assert await stored_district(test_container, case_id) == "DT4"


async def test_a_district_on_a_closed_case_is_a_conflict(
    api_client: AsyncClient, test_container: Container, seeded: None
) -> None:
    case_id = await open_case(api_client, "dc-open-8")
    closed = await api_client.post(
        f"/fhir/ServiceRequest/{case_id}/$close",
        json={
            "resourceType": "Parameters",
            "parameter": [{"name": "outcome", "valueCode": "declined"}],
        },
        headers=headers("dc-close-1"),
    )
    assert closed.status_code == 200, closed.text

    response = await put(api_client, case_id, district_body("BH1"), "dc-put-4", Role.ADVISOR)

    assert response.status_code == 409


# ------------------------------------------------------------------------------- roles, tenants


async def test_every_role_but_an_advisor_and_a_clinical_advisor_is_refused_the_same_way(
    api_client: AsyncClient, test_container: Container, seeded: None
) -> None:
    case_id = await open_case(api_client, "dc-open-9")
    refused: dict[Role, bytes] = {}
    for role in Role:
        response = await put(
            api_client, case_id, district_body("DT1"), f"dc-role-{role.value}", role
        )
        if role in (Role.ADVISOR, Role.CLINICAL):
            continue
        if role in EDGE_REFUSED:
            assert response.status_code == 401, role
        else:
            assert response.status_code == 404, (role, response.status_code)
            refused[role] = response.content
    assert len(set(refused.values())) == 1
    assert len(refused) == len(Role) - 2 - len(EDGE_REFUSED)


@pytest.mark.parametrize("role", [Role.ADVISOR, Role.CLINICAL])
async def test_an_advisor_and_a_clinical_advisor_may_choose_a_district(
    api_client: AsyncClient, test_container: Container, seeded: None, role: Role
) -> None:
    case_id = await open_case(api_client, f"dc-open-{role.value}")

    response = await put(api_client, case_id, district_body("DT2"), f"dc-ok-{role.value}", role)

    assert response.status_code == 200, response.text
    assert await stored_district(test_container, case_id) == "DT2"


async def test_a_refused_role_changes_no_district(
    api_client: AsyncClient, test_container: Container, seeded: None
) -> None:
    case_id = await open_case(api_client, "dc-open-10")
    for role in (Role.EXEC, Role.LEAD, Role.REPORTER, Role.WALL, Role.OWNER, Role.SUPPORT):
        await put(api_client, case_id, district_body("DT1"), f"dc-no-{role.value}", role)

    assert await stored_district(test_container, case_id) == "DT4"


async def test_another_tenants_case_is_the_one_404_for_a_district_and_stays_as_it_was(
    api_client: AsyncClient, seeded: None, uow_factory_b: UnitOfWorkFactory
) -> None:
    async with uow_factory_b() as uow:
        await uow.cases.add(
            Case(
                id=B_CASE_ID,
                reference="7392",
                referrer_type=ReferrerType.GP,
                age_band=AgeBand.A16_64,
                postcode="DT9",
                needs=(NeedCategory.WOUND_CARE,),
                urgency=Urgency.PLANNED,
                scores=(),
                opened_at=datetime(2026, 10, 23, 13, 0, tzinfo=UTC),
            )
        )
        await uow.commit()

    foreign = await put(api_client, B_CASE_ID, district_body("DT1"), "dc-foreign", Role.ADVISOR)
    unknown = await put(
        api_client, "no-such-case", district_body("DT1"), "dc-unknown", Role.ADVISOR
    )

    assert foreign.status_code == unknown.status_code == 404
    assert foreign.json() == unknown.json()
    async with uow_factory_b() as uow:
        stored = await uow.cases.get(B_CASE_ID)
    assert stored is not None and stored.postcode == "DT9"
