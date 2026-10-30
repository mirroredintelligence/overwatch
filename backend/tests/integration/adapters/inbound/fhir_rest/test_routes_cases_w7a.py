"""The advisor case routes added in W7A (A1 to A5, A8) against real Neo4j through the API client.

A1 reads one case; A2 opens a case with nothing in it; A3 saves the age band and the referrer on a
later PUT (so the age filter runs); A4 keeps planned as planned; A5 stores and reads back the
referrer's scores; A8 answers the close time. The two-tenant tests seed tenant B through its own
unit of work and ask for its case with tenant A's token: the same 404 as an unknown id. Synthetic
values only; the case holds the postcode district DT4 and no name, identifier, birth date or
telecom.
"""

import copy
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import AsyncClient

from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.domain.codes import AgeBand, NeedCategory, ReferrerType, Role, Urgency
from diucs.domain.model.case import Case
from tests.integration.adapters.inbound.fhir_rest.test_routes_cases import (
    CASE_BODY,
    UCR_WEST,
    fresh_cases,
    route_state,
    seeded,
)
from tests.support.api import token_headers

__all__ = ["fresh_cases", "route_state", "seeded"]

pytestmark = pytest.mark.asyncio(loop_scope="session")

BASE = "https://diucs.example/StructureDefinition"
AGE_BAND = f"{BASE}/age-band"
REFERRER = f"{BASE}/referrer-type"
URGENCY = f"{BASE}/urgency"
SCORE = f"{BASE}/score"
CLOSED_AT = f"{BASE}/closed-at"
NEED_SYSTEM = "https://diucs.example/CodeSystem/need-category"
EMPTY_CASE: dict[str, Any] = {"resourceType": "ServiceRequest"}
B_CASE_ID = "case-of-tenant-b"
B_REFERENCE = "7391"


def headers(key: str, role: Role = Role.ADVISOR, **extra: str) -> dict[str, str]:
    return {**token_headers(role=role), "Idempotency-Key": key, **extra}


def score(method: str, key: str, value: object) -> dict[str, Any]:
    return {
        "url": SCORE,
        "extension": [{"url": "method", "valueCode": method}, {"url": "value", key: value}],
    }


def case_body(**changes: Any) -> dict[str, Any]:
    body = copy.deepcopy(CASE_BODY)
    body.update(changes)
    return body


def extension(resource: dict[str, Any], url: str) -> dict[str, Any] | None:
    found = [item for item in resource.get("extension", []) if item["url"] == url]
    return found[0] if found else None


async def open_empty(client: AsyncClient, key: str = "open-empty") -> str:
    response = await client.post("/fhir/ServiceRequest", json=EMPTY_CASE, headers=headers(key))
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def put(client: AsyncClient, case_id: str, body: dict[str, Any], key: str) -> Any:
    return await client.put(
        f"/fhir/ServiceRequest/{case_id}", json=body, headers=headers(key, **{"If-Match": 'W/"1"'})
    )


# A1: the case is read.


@pytest.mark.parametrize("role", [Role.ADVISOR, Role.CLINICAL])
async def test_a_case_is_read_by_the_advisor_and_the_clinical_advisor(
    api_client: AsyncClient, seeded: None, role: Role
) -> None:
    opened = await api_client.post(
        "/fhir/ServiceRequest", json=CASE_BODY, headers=headers("a1-open")
    )
    case_id = opened.json()["id"]

    response = await api_client.get(
        f"/fhir/ServiceRequest/{case_id}", headers=token_headers(role=role)
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == case_id
    assert body["status"] == "active"
    assert body["priority"] == "urgent"
    assert body["contained"][0]["address"] == [{"postalCode": "DT4"}]
    assert extension(body["contained"][0], AGE_BAND) == {"url": AGE_BAND, "valueCode": "80+"}
    assert extension(body, REFERRER) == {"url": REFERRER, "valueCode": "ambulance-crew"}
    assert [c["code"] for r in body["reasonCode"] for c in r["coding"]] == [
        "fall-no-injury",
        "frailty",
    ]
    assert body["identifier"][0]["value"] == opened.json()["identifier"][0]["value"]
    assert len(body["identifier"][0]["value"]) == 4
    assert body["authoredOn"].startswith("2026-10-23T") and body["authoredOn"].endswith("Z")
    assert response.headers["etag"] == 'W/"1"'
    assert response.headers["cache-control"] == "no-store"
    assert "name" not in body["contained"][0]


async def test_an_unknown_case_is_a_404(api_client: AsyncClient, seeded: None) -> None:
    response = await api_client.get(
        "/fhir/ServiceRequest/no-such-case", headers=token_headers(role=Role.ADVISOR)
    )

    assert response.status_code == 404


async def test_another_tenants_case_reads_as_the_same_404_as_an_unknown_id(
    api_client: AsyncClient, seeded: None, uow_factory_b: UnitOfWorkFactory
) -> None:
    async with uow_factory_b() as uow:
        await uow.cases.add(
            Case(
                id=B_CASE_ID,
                reference=B_REFERENCE,
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

    foreign = await api_client.get(
        f"/fhir/ServiceRequest/{B_CASE_ID}", headers=token_headers(role=Role.ADVISOR)
    )
    unknown = await api_client.get(
        "/fhir/ServiceRequest/no-such-case", headers=token_headers(role=Role.ADVISOR)
    )

    assert foreign.status_code == 404
    assert foreign.json() == unknown.json()
    assert "DT9" not in foreign.text
    assert B_REFERENCE not in foreign.text


async def test_a_put_to_another_tenants_case_is_a_404_and_changes_nothing(
    api_client: AsyncClient, seeded: None, uow_factory_b: UnitOfWorkFactory
) -> None:
    async with uow_factory_b() as uow:
        await uow.cases.add(
            Case(
                id=B_CASE_ID,
                reference=B_REFERENCE,
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

    response = await put(api_client, B_CASE_ID, case_body(), "a1-foreign-put")

    assert response.status_code == 404
    async with uow_factory_b() as uow:
        stored = await uow.cases.get(B_CASE_ID)
    assert stored is not None
    assert stored.postcode == "DT9"
    assert stored.age_band is AgeBand.A16_64
    assert stored.urgency is Urgency.PLANNED


# A2: a case opens with nothing in it.


async def test_a_case_opens_with_nothing_in_it(
    api_client: AsyncClient, seeded: None, test_container: Any
) -> None:
    response = await api_client.post(
        "/fhir/ServiceRequest", json=EMPTY_CASE, headers=headers("a2-open")
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert extension(body, REFERRER) is None
    assert "priority" not in body
    assert "reasonCode" not in body
    async with test_container.uow_factory() as uow:
        stored = await uow.cases.get(body["id"])
    assert stored is not None
    assert stored.referrer_type is None
    assert stored.needs == ()


async def test_an_empty_open_replays_by_its_key(api_client: AsyncClient, seeded: None) -> None:
    first = await open_empty(api_client, "a2-replay")
    second = await open_empty(api_client, "a2-replay")

    assert first == second


async def test_an_open_with_a_referrer_that_is_not_listed_is_a_400(
    api_client: AsyncClient, seeded: None
) -> None:
    body = {
        "resourceType": "ServiceRequest",
        "extension": [{"url": REFERRER, "valueCode": "neighbour"}],
    }

    response = await api_client.post("/fhir/ServiceRequest", json=body, headers=headers("a2-bad"))

    assert response.status_code == 400
    assert "neighbour" not in response.text


async def test_options_are_refused_for_a_case_with_no_referrer(
    api_client: AsyncClient, seeded: None
) -> None:
    case_id = await open_empty(api_client, "a2-options")
    update = case_body()
    update["extension"] = []
    saved = await put(api_client, case_id, update, "a2-options-put")
    assert saved.status_code == 200, saved.text

    response = await api_client.post(
        "/fhir/HealthcareService/$filter-options",
        json={
            "resourceType": "Parameters",
            "parameter": [
                {"name": "case", "valueReference": {"reference": f"ServiceRequest/{case_id}"}}
            ],
        },
        headers=headers("a2-options-filter"),
    )

    assert response.status_code == 400
    assert "referrer_type" in response.text


# A3: the PUT keeps the age band and the referrer, so the age filter applies.


async def test_a_put_keeps_the_age_band_and_the_referrer(
    api_client: AsyncClient, seeded: None
) -> None:
    case_id = await open_empty(api_client, "a3-open")

    saved = await put(api_client, case_id, case_body(), "a3-put")
    read = await api_client.get(
        f"/fhir/ServiceRequest/{case_id}", headers=token_headers(role=Role.ADVISOR)
    )

    assert saved.status_code == 200, saved.text
    for body in (saved.json(), read.json()):
        assert extension(body["contained"][0], AGE_BAND) == {"url": AGE_BAND, "valueCode": "80+"}
        assert extension(body, REFERRER) == {"url": REFERRER, "valueCode": "ambulance-crew"}


async def test_a_put_that_leaves_the_age_band_out_keeps_the_one_stored(
    api_client: AsyncClient, seeded: None
) -> None:
    case_id = await open_empty(api_client, "a3-keep-open")
    await put(api_client, case_id, case_body(), "a3-keep-first")
    again = case_body()
    del again["contained"][0]["extension"]

    saved = await put(api_client, case_id, again, "a3-keep-second")

    assert saved.status_code == 200, saved.text
    assert extension(saved.json()["contained"][0], AGE_BAND) == {
        "url": AGE_BAND,
        "valueCode": "80+",
    }


async def _options(client: AsyncClient, case_id: str, key: str) -> list[dict[str, Any]]:
    response = await client.post(
        "/fhir/HealthcareService/$filter-options",
        json={
            "resourceType": "Parameters",
            "parameter": [
                {"name": "case", "valueReference": {"reference": f"ServiceRequest/{case_id}"}}
            ],
        },
        headers=headers(key),
    )
    assert response.status_code == 200, response.text
    parameters: list[dict[str, Any]] = response.json()["parameter"]
    return parameters


def _names(parameters: list[dict[str, Any]], which: str) -> list[str]:
    return [
        part["valueString"]
        for item in parameters
        if item["name"] == which
        for part in item["part"]
        if part["name"] == "name"
    ]


async def test_the_age_filter_applies_to_the_age_band_saved_by_a_put(
    api_client: AsyncClient, seeded: None
) -> None:
    child = await open_empty(api_client, "a3-child-open")
    older = await open_empty(api_client, "a3-older-open")
    young_body = case_body()
    young_body["contained"][0]["extension"][0]["valueCode"] = "0-15"
    await put(api_client, child, young_body, "a3-child-put")
    await put(api_client, older, case_body(), "a3-older-put")

    for_child = await _options(api_client, child, "a3-child-filter")
    for_older = await _options(api_client, older, "a3-older-filter")

    # UCR West takes people from 18 (its criteria), so a child is outside them.
    assert "UCR West" not in _names(for_child, "option")
    assert "UCR West" in _names(for_child, "notSuitable")
    assert "UCR West" in _names(for_older, "option")
    assert UCR_WEST == "svc-ucr-west"


# A4: planned is stored as planned.


async def test_a_planned_case_is_stored_and_read_back_as_planned(
    api_client: AsyncClient, seeded: None, test_container: Any
) -> None:
    case_id = await open_empty(api_client, "a4-open")
    body = case_body(priority="routine")
    body["extension"].append({"url": URGENCY, "valueCode": "planned"})

    saved = await put(api_client, case_id, body, "a4-put")
    read = await api_client.get(
        f"/fhir/ServiceRequest/{case_id}", headers=token_headers(role=Role.ADVISOR)
    )

    assert saved.status_code == 200, saved.text
    for answer in (saved.json(), read.json()):
        assert answer["priority"] == "routine"
        assert extension(answer, URGENCY) == {"url": URGENCY, "valueCode": "planned"}
    async with test_container.uow_factory() as uow:
        stored = await uow.cases.get(case_id)
    assert stored is not None
    assert stored.urgency is Urgency.PLANNED


async def test_routine_alone_is_still_today_and_urgent_is_within_2_hrs(
    api_client: AsyncClient, seeded: None
) -> None:
    case_id = await open_empty(api_client, "a4-compat-open")

    today = await put(api_client, case_id, case_body(priority="routine"), "a4-compat-1")
    urgent = await put(api_client, case_id, case_body(priority="urgent"), "a4-compat-2")

    assert extension(today.json(), URGENCY) == {"url": URGENCY, "valueCode": "today"}
    assert extension(urgent.json(), URGENCY) == {"url": URGENCY, "valueCode": "within-2-hrs"}


async def test_an_urgency_that_disagrees_with_its_priority_is_a_400(
    api_client: AsyncClient, seeded: None
) -> None:
    case_id = await open_empty(api_client, "a4-clash-open")
    body = case_body(priority="urgent")
    body["extension"].append({"url": URGENCY, "valueCode": "planned"})

    response = await put(api_client, case_id, body, "a4-clash")

    assert response.status_code == 400


# A5: scores are stored and read back.


async def test_scores_are_stored_and_read_back(
    api_client: AsyncClient, seeded: None, test_container: Any
) -> None:
    case_id = await open_empty(api_client, "a5-open")
    body = case_body()
    body["extension"] += [
        score("news2", "valueInteger", 5),
        score("pathways-dx", "valueString", "DX123"),
    ]

    saved = await put(api_client, case_id, body, "a5-put")
    read = await api_client.get(
        f"/fhir/ServiceRequest/{case_id}", headers=token_headers(role=Role.CLINICAL)
    )

    assert saved.status_code == 200, saved.text
    expected = [score("news2", "valueInteger", 5), score("pathways-dx", "valueString", "DX123")]
    for answer in (saved.json(), read.json()):
        assert [e for e in answer["extension"] if e["url"] == SCORE] == expected
    async with test_container.uow_factory() as uow:
        stored = await uow.cases.get(case_id)
    assert stored is not None
    assert len(stored.scores) == 2


async def test_the_same_scores_again_are_accepted_and_other_scores_are_refused(
    api_client: AsyncClient, seeded: None
) -> None:
    case_id = await open_empty(api_client, "a5-again-open")
    body = case_body()
    body["extension"].append(score("news2", "valueInteger", 5))
    await put(api_client, case_id, body, "a5-again-1")

    same = await put(api_client, case_id, body, "a5-again-2")
    other_body = case_body()
    other_body["extension"].append(score("news2", "valueInteger", 6))
    other = await put(api_client, case_id, other_body, "a5-again-3")

    assert same.status_code == 200, same.text
    assert other.status_code == 400
    assert "recorded scores cannot change" in other.text


async def test_a_put_that_leaves_the_scores_out_keeps_them(
    api_client: AsyncClient, seeded: None
) -> None:
    case_id = await open_empty(api_client, "a5-keep-open")
    body = case_body()
    body["extension"].append(score("cfs", "valueInteger", 6))
    await put(api_client, case_id, body, "a5-keep-1")

    kept = await put(api_client, case_id, case_body(), "a5-keep-2")

    assert [e for e in kept.json()["extension"] if e["url"] == SCORE] == [
        score("cfs", "valueInteger", 6)
    ]


async def test_a_score_outside_its_range_is_a_400_that_does_not_echo_it(
    api_client: AsyncClient, seeded: None
) -> None:
    case_id = await open_empty(api_client, "a5-range-open")
    body = case_body()
    body["extension"].append(score("news2", "valueInteger", 99))

    response = await put(api_client, case_id, body, "a5-range")

    assert response.status_code == 400
    assert "99" not in response.text


# A8: the close answers when it closed.


async def test_close_answers_the_close_time_and_the_outcome(
    api_client: AsyncClient, seeded: None
) -> None:
    opened = await api_client.post(
        "/fhir/ServiceRequest", json=CASE_BODY, headers=headers("a8-open")
    )
    case_id = opened.json()["id"]

    closed = await api_client.post(
        f"/fhir/ServiceRequest/{case_id}/$close",
        json={
            "resourceType": "Parameters",
            "parameter": [{"name": "outcome", "valueCode": "declined"}],
        },
        headers=headers("a8-close"),
    )
    read = await api_client.get(
        f"/fhir/ServiceRequest/{case_id}", headers=token_headers(role=Role.ADVISOR)
    )

    assert closed.status_code == 200, closed.text
    for answer in (closed.json(), read.json()):
        assert answer["status"] == "completed"
        item = extension(answer, CLOSED_AT)
        assert item is not None
        assert item["valueDateTime"].endswith("Z")
        assert extension(answer, f"{BASE}/outcome") == {
            "url": f"{BASE}/outcome",
            "valueCode": "declined",
        }
        assert "reasonCode" not in answer
        assert "postalCode" not in str(answer)
