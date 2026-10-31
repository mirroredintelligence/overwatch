"""The score and version rules of the case routes (H-85, KI-815, H-192, KI-400), against real Neo4j
through the API client.

A PUT names the version it read as If-Match and a case at another version is 412 with nothing
written; a Pathways Dx code not on the list is refused with 400; a recorded score is corrected only
with a listed reason, and the answer says how many corrections the case has; an open with refused
details leaves no case. Another tenant's case is the same 404 as an unknown one. Sample values.
"""

import copy
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from neo4j import AsyncDriver

from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.domain.codes import AgeBand, NeedCategory, ReferrerType, Role, Urgency
from diucs.domain.model.case import Case
from diucs.domain.model.scores import News2
from tests.integration.adapters.inbound.fhir_rest.test_routes_cases import (
    CASE_BODY,
    fresh_cases,
    route_state,
    seeded,
)
from tests.integration.adapters.inbound.fhir_rest.test_routes_cases_w7a import (
    SCORE,
    current_version,
    extension,
    headers,
    put,
    score,
    with_dx_list,
)
from tests.support.api import token_headers
from tests.support.neo4j import count_nodes

__all__ = ["fresh_cases", "route_state", "seeded"]

pytestmark = pytest.mark.asyncio(loop_scope="session")

BASE = "https://diucs.example/StructureDefinition"
REASON = f"{BASE}/score-correction-reason"
CORRECTIONS = f"{BASE}/score-corrections"
B_CASE_ID = "case-of-tenant-b"


def body_with(*extensions: dict[str, Any]) -> dict[str, Any]:
    body = copy.deepcopy(CASE_BODY)
    body["extension"] = [*body["extension"], *extensions]
    return body


async def opened(
    client: AsyncClient, key: str = "open-1", body: dict[str, Any] | None = None
) -> str:
    response = await client.post(
        "/fhir/ServiceRequest", json=body or CASE_BODY, headers=headers(key)
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


# H-192: the version.


async def test_a_put_naming_a_stale_version_is_412_and_changes_nothing(
    api_client: AsyncClient, seeded: None
) -> None:
    case_id = await opened(api_client)
    read = await current_version(api_client, case_id)
    first = await put(
        api_client, case_id, body_with(score("news2", "valueInteger", 2)), "v-1", read
    )
    assert first.status_code == 200, first.text

    stale = await put(
        api_client, case_id, body_with(score("news2", "valueInteger", 3)), "v-2", read
    )

    assert stale.status_code == 412
    after = await api_client.get(
        f"/fhir/ServiceRequest/{case_id}", headers=token_headers(role=Role.ADVISOR)
    )
    assert extension(after.json(), SCORE) == score("news2", "valueInteger", 2)


async def test_a_put_naming_the_current_version_is_applied_and_answers_the_new_version(
    api_client: AsyncClient, seeded: None
) -> None:
    case_id = await opened(api_client)
    read = await current_version(api_client, case_id)

    saved = await put(
        api_client, case_id, body_with(score("news2", "valueInteger", 2)), "v-1", read
    )

    assert saved.status_code == 200, saved.text
    assert saved.headers["etag"] != read
    assert saved.headers["etag"] == await current_version(api_client, case_id)


async def test_the_open_answers_the_version_a_read_gives(
    api_client: AsyncClient, seeded: None
) -> None:
    response = await api_client.post("/fhir/ServiceRequest", json=CASE_BODY, headers=headers("o-1"))

    assert response.headers["etag"] == await current_version(api_client, response.json()["id"])


async def test_a_close_naming_a_stale_version_is_412_and_a_close_naming_none_closes(
    api_client: AsyncClient, seeded: None
) -> None:
    case_id = await opened(api_client)
    read = await current_version(api_client, case_id)
    await put(api_client, case_id, body_with(score("news2", "valueInteger", 2)), "v-1", read)
    parameters = {
        "resourceType": "Parameters",
        "parameter": [{"name": "outcome", "valueCode": "declined"}],
    }

    stale = await api_client.post(
        f"/fhir/ServiceRequest/{case_id}/$close",
        json=parameters,
        headers=headers("close-stale", **{"If-Match": read}),
    )
    closed = await api_client.post(
        f"/fhir/ServiceRequest/{case_id}/$close", json=parameters, headers=headers("close-ok")
    )

    assert stale.status_code == 412
    assert closed.status_code == 200, closed.text
    assert closed.headers["etag"]


async def test_a_put_to_another_tenants_case_is_the_same_404_whatever_the_version(
    api_client: AsyncClient, seeded: None, uow_factory_b: UnitOfWorkFactory
) -> None:
    async with uow_factory_b() as uow:
        await uow.cases.add(
            Case(
                id=B_CASE_ID,
                reference="7391",
                referrer_type=ReferrerType.GP,
                age_band=AgeBand.A16_64,
                postcode="DT9",
                needs=(NeedCategory.WOUND_CARE,),
                urgency=Urgency.PLANNED,
                scores=(News2(2),),
                opened_at=datetime(2026, 10, 23, 13, 0, tzinfo=UTC),
            )
        )
        found = await uow.cases.get_versioned(B_CASE_ID)
        await uow.commit()
    assert found is not None

    response = await put(
        api_client,
        B_CASE_ID,
        body_with(score("news2", "valueInteger", 9), {"url": REASON, "valueCode": "typing-error"}),
        "v-foreign",
        f'W/"{found[1]}"',
    )

    assert response.status_code == 404
    async with uow_factory_b() as uow:
        again = await uow.cases.get_versioned(B_CASE_ID)
    assert again is not None and again[1] == found[1] and again[0].scores == (News2(2),)


# H-85: the Pathways Dx code.


async def test_a_dx_code_not_on_the_list_is_a_400_and_nothing_is_recorded(
    api_client: AsyncClient, api_app: FastAPI, seeded: None
) -> None:
    with_dx_list(api_app)
    case_id = await opened(api_client)

    refused = await put(
        api_client, case_id, body_with(score("pathways-dx", "valueString", "DxSAMPLE99")), "dx-1"
    )

    assert refused.status_code == 400
    assert "DxSAMPLE99" not in refused.text
    after = await api_client.get(
        f"/fhir/ServiceRequest/{case_id}", headers=token_headers(role=Role.ADVISOR)
    )
    assert extension(after.json(), SCORE) is None


async def test_a_dx_code_on_the_list_is_recorded_and_read_back(
    api_client: AsyncClient, api_app: FastAPI, seeded: None
) -> None:
    with_dx_list(api_app)
    case_id = await opened(api_client)

    saved = await put(
        api_client, case_id, body_with(score("pathways-dx", "valueString", "DxSAMPLE01")), "dx-2"
    )

    assert saved.status_code == 200, saved.text
    assert extension(saved.json(), SCORE) == score("pathways-dx", "valueString", "DxSAMPLE01")


async def test_an_open_with_a_dx_code_not_on_the_list_is_a_400_and_leaves_no_case(
    api_client: AsyncClient, api_app: FastAPI, seeded: None, neo4j_driver: AsyncDriver
) -> None:
    with_dx_list(api_app)

    refused = await api_client.post(
        "/fhir/ServiceRequest",
        json=body_with(score("pathways-dx", "valueString", "DxSAMPLE99")),
        headers=headers("dx-open"),
    )

    assert refused.status_code == 400
    assert await count_nodes(neo4j_driver, "ServiceRequest") == 0


async def test_an_open_with_refused_details_leaves_no_case_and_no_patient_stub(
    api_client: AsyncClient, seeded: None, neo4j_driver: AsyncDriver
) -> None:
    bad = copy.deepcopy(CASE_BODY)
    bad["contained"][0]["address"] = [{"postalCode": "not a postcode"}]

    refused = await api_client.post("/fhir/ServiceRequest", json=bad, headers=headers("bad-open"))

    assert refused.status_code == 400
    assert await count_nodes(neo4j_driver, "ServiceRequest") == 0
    assert await count_nodes(neo4j_driver, "Patient") == 0


# Q7: the correction.


async def test_a_recorded_score_is_corrected_with_a_listed_reason_and_the_answer_says_so(
    api_client: AsyncClient, seeded: None
) -> None:
    case_id = await opened(api_client)
    await put(api_client, case_id, body_with(score("news2", "valueInteger", 2)), "c-0")

    corrected = await put(
        api_client,
        case_id,
        body_with(score("news2", "valueInteger", 5), {"url": REASON, "valueCode": "typing-error"}),
        "c-1",
    )

    assert corrected.status_code == 200, corrected.text
    assert extension(corrected.json(), SCORE) == score("news2", "valueInteger", 5)
    assert extension(corrected.json(), CORRECTIONS) == {"url": CORRECTIONS, "valueInteger": 1}
    again = await api_client.get(
        f"/fhir/ServiceRequest/{case_id}", headers=token_headers(role=Role.ADVISOR)
    )
    assert extension(again.json(), CORRECTIONS) == {"url": CORRECTIONS, "valueInteger": 1}


async def test_changing_a_recorded_score_with_no_reason_is_a_400(
    api_client: AsyncClient, seeded: None
) -> None:
    case_id = await opened(api_client)
    await put(api_client, case_id, body_with(score("news2", "valueInteger", 2)), "c-0")

    refused = await put(
        api_client, case_id, body_with(score("news2", "valueInteger", 5)), "c-no-reason"
    )

    assert refused.status_code == 400
    assert refused.json()["issue"][0]["expression"] == ["score_correction_reason"]


async def test_a_reason_that_is_not_listed_is_a_400(api_client: AsyncClient, seeded: None) -> None:
    case_id = await opened(api_client)
    await put(api_client, case_id, body_with(score("news2", "valueInteger", 2)), "c-0")

    refused = await put(
        api_client,
        case_id,
        body_with(score("news2", "valueInteger", 5), {"url": REASON, "valueCode": "my words"}),
        "c-bad-reason",
    )

    assert refused.status_code == 400
    assert "my words" not in refused.text


@pytest.mark.parametrize("role", [Role.ADVISOR, Role.CLINICAL])
async def test_both_case_roles_may_correct_a_score(
    api_client: AsyncClient, seeded: None, role: Role
) -> None:
    case_id = await opened(api_client)
    await put(api_client, case_id, body_with(score("news2", "valueInteger", 2)), "c-0")
    read = await api_client.get(f"/fhir/ServiceRequest/{case_id}", headers=token_headers(role=role))

    response = await api_client.put(
        f"/fhir/ServiceRequest/{case_id}",
        json=body_with(
            score("news2", "valueInteger", 6), {"url": REASON, "valueCode": "referrer-corrected"}
        ),
        headers=headers(f"c-{role}", role, **{"If-Match": read.headers["etag"]}),
    )

    assert response.status_code == 200, response.text


# H-322: the summary route.


def _rows(response: Any) -> dict[str, str]:
    rows: dict[str, str] = {}
    for item in response.json()["parameter"]:
        if item["name"] == "row":
            values = {part["name"]: part["valueString"] for part in item["part"]}
            rows[values["label"]] = values["value"]
    return rows


async def test_the_summary_of_an_open_case_names_the_destination_and_the_data_age(
    api_client: AsyncClient, seeded: None
) -> None:
    case_id = await opened(api_client)

    response = await api_client.get(
        f"/fhir/ServiceRequest/{case_id}/$summary?destination=svc-ucr-west",
        headers=token_headers(role=Role.ADVISOR),
    )

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    rows = _rows(response)
    assert rows["Postcode"] == "DT4"
    assert rows["Destination"] == "UCR West"
    assert "Data age" in rows
    assert "DT4 8XX" not in response.text


async def test_the_summary_without_a_destination_leaves_those_rows_out(
    api_client: AsyncClient, seeded: None
) -> None:
    case_id = await opened(api_client)

    response = await api_client.get(
        f"/fhir/ServiceRequest/{case_id}/$summary", headers=token_headers(role=Role.CLINICAL)
    )

    assert response.status_code == 200, response.text
    assert not {"Destination", "Booked", "Data age"} & set(_rows(response))


async def test_the_summary_of_a_closed_case_is_409_and_of_another_tenants_case_is_404(
    api_client: AsyncClient, seeded: None
) -> None:
    case_id = await opened(api_client)
    await api_client.post(
        f"/fhir/ServiceRequest/{case_id}/$close",
        json={
            "resourceType": "Parameters",
            "parameter": [{"name": "outcome", "valueCode": "declined"}],
        },
        headers=headers("sum-close"),
    )

    closed = await api_client.get(
        f"/fhir/ServiceRequest/{case_id}/$summary", headers=token_headers(role=Role.ADVISOR)
    )
    foreign = await api_client.get(
        f"/fhir/ServiceRequest/{B_CASE_ID}/$summary", headers=token_headers(role=Role.ADVISOR)
    )

    assert closed.status_code == 409
    assert foreign.status_code == 404
