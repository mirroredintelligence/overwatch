"""One clinical advice request, and the clinician's Mine and Done lists (W7A-B1, B2) against real
Neo4j through the API client.

B1: `GET /fhir/Task/{id}` answers one request to the advisor who asked and to a clinician, with the
case's number, age band, needs, urgency and NEWS2 and no patient identifier, and with the advice
once it is given. Another advisor, a lead, an executive or a reporter read nothing (the same 404 as
an unknown id). B2: `GET /fhir/Task?code=clinical-advice&status=in-progress` lists the requests the
clinician holds, `status=completed` the ones they advised; the queue shows the case's age band,
needs and NEWS2. Two tenants: tenant B holds a request and its case, and tenant A reads neither.
Sample values only; the advice note is a sample sentence.
"""

from datetime import timedelta
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient

from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.domain.codes import (
    AgeBand,
    NeedCategory,
    PractitionerRoleCode,
    ReferrerType,
    Role,
    Urgency,
    code_system_url,
)
from diucs.domain.model.case import Case
from diucs.domain.model.clinical import ClinicalAdvice, ClinicalRequestRecord
from diucs.domain.model.people import Practitioner, PractitionerRole
from diucs.domain.model.scores import News2
from diucs.domain.rules.clinical_queue import ClinicalRequest
from tests.integration.adapters.inbound.fhir_rest.test_routes_clinical import (
    clinical_world,
    test_container,
)
from tests.support.api import R01_TEST_NOW, token_headers

__all__ = ["clinical_world", "test_container"]

pytestmark = pytest.mark.asyncio(loop_scope="session")

NOTE = "Go ahead: the sample referral fits the service."
CASE = "case-first"
REFERENCE = "4821"
OTHER_CASE = "case-second"
B_CASE = "case-tenant-b"
B_REFERENCE = "7391"
ADVISOR_1 = "adv-1"
ADVISOR_2 = "adv-2"
CLIN_1 = "clin-1"
CLIN_2 = "clin-2"
QUEUE = "/fhir/Task"


def _input(name: str) -> str:
    return code_system_url(f"task-input/{name}")


def values(task: dict[str, Any], name: str) -> list[Any]:
    """Every value of the Task's extensions of this name (a need can repeat)."""
    found: list[Any] = []
    for item in task.get("extension", []):
        if item["url"] == _input(name):
            found.append(next(v for k, v in item.items() if k.startswith("value")))
    return found


def _case(case_id: str, reference: str, **changes: Any) -> Case:
    fields: dict[str, Any] = {
        "id": case_id,
        "reference": reference,
        "referrer_type": ReferrerType.GP,
        "age_band": AgeBand.A80_PLUS,
        "postcode": "DT4",
        "needs": (NeedCategory.FRAILTY, NeedCategory.FALL_NO_INJURY),
        "urgency": Urgency.WITHIN_2_HRS,
        "scores": (News2(5),),
        "opened_at": R01_TEST_NOW - timedelta(hours=1),
    }
    fields.update(changes)
    return Case(**fields)


def _request(
    request_id: str,
    case_id: str = CASE,
    requester: str = ADVISOR_1,
    taken_by: str | None = None,
    taken_minutes_ago: int = 3,
    advised: bool = False,
    urgency: str = "now",
) -> ClinicalRequestRecord:
    taken_at = None if taken_by is None else R01_TEST_NOW - timedelta(minutes=taken_minutes_ago)
    advised_at = R01_TEST_NOW - timedelta(minutes=1) if advised else None
    advice = None
    if advised and taken_by is not None:
        advice = ClinicalAdvice(
            choice="go-ahead",
            reason="within-criteria-on-judgement",
            note_handle=None,
            clinician_id=taken_by,
            at=R01_TEST_NOW - timedelta(minutes=1),
        )
    return ClinicalRequestRecord(
        request=ClinicalRequest(
            id=request_id,
            case_id=case_id,
            urgency=urgency,
            requested_at=R01_TEST_NOW - timedelta(minutes=8),
            taken_by=taken_by,
            taken_at=taken_at,
            advised_at=advised_at,
        ),
        requester_id=requester,
        why="borderline-criteria",
        snapshot_ref=None,
        advice=advice,
    )


async def _people(factory: UnitOfWorkFactory, *ids: str) -> None:
    async with factory() as uow:
        for person in ids:
            await uow.people.save_practitioner(
                Practitioner(id=person, active=True, display_name=person, phone_hash=None)
            )
            if person.startswith("clin"):
                await uow.people.save_role(
                    PractitionerRole(
                        id=f"role-{person}",
                        practitioner_id=person,
                        service_id=None,
                        code=PractitionerRoleCode.CLINICAL_LEAD,
                        active=True,
                        channel=None,
                        period_start=R01_TEST_NOW,
                    )
                )
        await uow.commit()


@pytest_asyncio.fixture(loop_scope="session")
async def world(clinical_world: None, uow_factory_a: UnitOfWorkFactory) -> None:
    """Two advisors, two clinicians, two cases, and the requests of the tests below: waiting (w1),
    taken by clin-1 (t1), taken by clin-2 (t2), taken by clin-1 eleven minutes ago (lapsed),
    advised by clin-1 with a note (a1), advised by clin-2 (a2), and one of the second advisor
    (o1)."""
    await _people(uow_factory_a, ADVISOR_1, ADVISOR_2, CLIN_2)
    async with uow_factory_a() as uow:
        await uow.cases.add(_case(CASE, REFERENCE))
        await uow.cases.add(_case(OTHER_CASE, "4822", age_band=AgeBand.A16_64, scores=()))
        await uow.clinical_requests.add(_request("w1"))
        await uow.clinical_requests.add(_request("t1", taken_by=CLIN_1))
        await uow.clinical_requests.add(_request("t2", taken_by=CLIN_2))
        await uow.clinical_requests.add(_request("lapsed", taken_by=CLIN_1, taken_minutes_ago=11))
        await uow.clinical_requests.add(_request("o1", OTHER_CASE, ADVISOR_2))
        handle = await uow.protected_text.put("clinical-note", "a1", NOTE)
        advised = _request("a1", taken_by=CLIN_1, advised=True)
        assert advised.advice is not None
        await uow.clinical_requests.add(
            ClinicalRequestRecord(
                request=advised.request,
                requester_id=ADVISOR_1,
                why=advised.why,
                snapshot_ref=None,
                advice=ClinicalAdvice(
                    choice="go-ahead",
                    reason="within-criteria-on-judgement",
                    note_handle=handle,
                    clinician_id=CLIN_1,
                    at=advised.advice.at,
                ),
            )
        )
        await uow.clinical_requests.add(_request("a2", taken_by=CLIN_2, advised=True))
        await uow.commit()


def _as(tenant_id: str, role: Role, sub: str) -> dict[str, str]:
    return token_headers(tenant_id, role, sub=sub)


async def _read(client: AsyncClient, tenant_id: str, request_id: str, role: Role, sub: str) -> Any:
    return await client.get(f"/fhir/Task/{request_id}", headers=_as(tenant_id, role, sub))


async def _list(client: AsyncClient, tenant_id: str, status: str, sub: str = CLIN_1) -> Any:
    return await client.get(
        QUEUE,
        params={"code": "clinical-advice", "status": status},
        headers=_as(tenant_id, Role.CLINICAL, sub),
    )


def _ids(response: Any) -> list[str]:
    return [entry["resource"]["id"] for entry in response.json()["entry"]]


# B1: one request.


async def test_the_advisor_who_asked_reads_the_request_with_the_case_details(
    api_client: AsyncClient, world: None, tenant_id: str
) -> None:
    response = await _read(api_client, tenant_id, "w1", Role.ADVISOR, ADVISOR_1)

    assert response.status_code == 200, response.text
    task = response.json()
    assert task["status"] == "requested"
    assert task["focus"] == {"reference": f"ServiceRequest/{CASE}"}
    assert values(task, "urgency") == ["now"]
    assert values(task, "why") == ["borderline-criteria"]
    assert values(task, "case-reference") == [REFERENCE]
    assert values(task, "age-band") == ["80+"]
    assert sorted(values(task, "need")) == ["fall-no-injury", "frailty"]
    assert values(task, "case-urgency") == ["within-2-hrs"]
    assert values(task, "news2") == [5]
    assert response.headers["cache-control"] == "no-store"


async def test_the_answer_holds_no_postcode_no_practitioner_and_no_advice_before_it_is_given(
    api_client: AsyncClient, world: None, tenant_id: str
) -> None:
    response = await _read(api_client, tenant_id, "w1", Role.ADVISOR, ADVISOR_1)

    for hidden in ("DT4", ADVISOR_1, ADVISOR_2, CLIN_1, CLIN_2, "requester", "owner"):
        assert hidden not in response.text, hidden
    assert values(response.json(), "advice-choice") == []
    assert values(response.json(), "returns-at") == []


async def test_a_clinician_reads_any_request(
    api_client: AsyncClient, world: None, tenant_id: str
) -> None:
    for request_id in ("w1", "t2", "a2", "o1"):
        response = await _read(api_client, tenant_id, request_id, Role.CLINICAL, CLIN_1)

        assert response.status_code == 200, (request_id, response.text)
        assert values(response.json(), "case-reference"), request_id


@pytest.mark.parametrize(
    ("role", "sub"),
    [
        (Role.ADVISOR, ADVISOR_2),
        (Role.LEAD, "prac-lead"),
        (Role.EXEC, "prac-exec"),
        (Role.REPORTER, "prac-reporter"),
        (Role.OWNER, "prac-owner"),
        (Role.WALL, "wall-1"),
    ],
)
async def test_no_one_else_reads_the_request_and_the_answer_is_the_unknown_ids(
    api_client: AsyncClient, world: None, tenant_id: str, role: Role, sub: str
) -> None:
    refused = await _read(api_client, tenant_id, "w1", role, sub)
    unknown = await _read(api_client, tenant_id, "no-such-request", role, sub)

    assert refused.status_code == 404
    assert refused.json() == unknown.json()
    assert REFERENCE not in refused.text


async def test_an_unknown_request_is_a_404_for_the_advisor_and_the_clinician(
    api_client: AsyncClient, world: None, tenant_id: str
) -> None:
    for role, sub in ((Role.ADVISOR, ADVISOR_1), (Role.CLINICAL, CLIN_1)):
        response = await _read(api_client, tenant_id, "no-such-request", role, sub)

        assert response.status_code == 404, role


async def test_a_taken_request_says_when_the_lock_ends_and_not_who_took_it(
    api_client: AsyncClient, world: None, tenant_id: str
) -> None:
    response = await _read(api_client, tenant_id, "t1", Role.ADVISOR, ADVISOR_1)

    task = response.json()
    assert task["status"] == "in-progress"
    # Taken three minutes ago, a ten-minute lock: it returns to the queue seven minutes from now.
    assert values(task, "returns-at") == ["2026-10-23T13:19:00Z"]
    assert CLIN_1 not in response.text


async def test_the_advisor_reads_the_advice_given_with_its_note(
    api_client: AsyncClient, world: None, tenant_id: str
) -> None:
    response = await _read(api_client, tenant_id, "a1", Role.ADVISOR, ADVISOR_1)

    task = response.json()
    assert task["status"] == "completed"
    assert values(task, "advice-choice") == ["go-ahead"]
    assert values(task, "advice-reason") == ["within-criteria-on-judgement"]
    assert values(task, "advice-note") == [NOTE]
    assert values(task, "advised-at") == ["2026-10-23T13:11:00Z"]
    assert values(task, "returns-at") == []
    assert CLIN_1 not in response.text


async def test_a_lapsed_lock_reads_as_waiting_again(
    api_client: AsyncClient, world: None, tenant_id: str
) -> None:
    response = await _read(api_client, tenant_id, "lapsed", Role.CLINICAL, CLIN_1)

    assert response.json()["status"] == "requested"
    assert values(response.json(), "returns-at") == []


async def test_tenant_bs_request_reads_as_the_same_404_in_tenant_a(
    api_client: AsyncClient,
    world: None,
    tenant_id: str,
    uow_factory_b: UnitOfWorkFactory,
) -> None:
    await _people(uow_factory_b, ADVISOR_1, CLIN_1)
    async with uow_factory_b() as uow:
        await uow.cases.add(
            _case(B_CASE, B_REFERENCE, age_band=AgeBand.A0_15, needs=(NeedCategory.WOUND_CARE,))
        )
        await uow.clinical_requests.add(_request("b-only", B_CASE, ADVISOR_1))
        await uow.commit()

    by_clinician = await _read(api_client, tenant_id, "b-only", Role.CLINICAL, CLIN_1)
    by_advisor = await _read(api_client, tenant_id, "b-only", Role.ADVISOR, ADVISOR_1)
    unknown = await _read(api_client, tenant_id, "no-such-request", Role.CLINICAL, CLIN_1)

    assert by_clinician.status_code == 404
    assert by_advisor.status_code == 404
    assert by_clinician.json() == unknown.json()
    assert B_REFERENCE not in by_clinician.text
    assert "wound-care" not in by_clinician.text


# B2: the queue, Mine and Done.


async def test_the_queue_shows_the_cases_age_band_needs_and_news2(
    api_client: AsyncClient, world: None, tenant_id: str
) -> None:
    response = await _list(api_client, tenant_id, "requested")

    assert response.status_code == 200, response.text
    # A lock that lapsed returns to the queue, so it is waiting again.
    assert sorted(_ids(response)) == ["lapsed", "o1", "w1"]
    tasks = {entry["resource"]["id"]: entry["resource"] for entry in response.json()["entry"]}
    assert values(tasks["w1"], "case-reference") == [REFERENCE]
    assert values(tasks["w1"], "age-band") == ["80+"]
    assert sorted(values(tasks["w1"], "need")) == ["fall-no-injury", "frailty"]
    assert values(tasks["w1"], "news2") == [5]
    assert values(tasks["o1"], "age-band") == ["16-64"]
    assert values(tasks["o1"], "news2") == []
    assert "DT4" not in response.text
    assert ADVISOR_1 not in response.text


async def test_mine_lists_the_requests_the_clinician_holds_and_not_a_lapsed_lock(
    api_client: AsyncClient, world: None, tenant_id: str
) -> None:
    mine = await _list(api_client, tenant_id, "in-progress", CLIN_1)
    theirs = await _list(api_client, tenant_id, "in-progress", CLIN_2)

    assert _ids(mine) == ["t1"]
    assert _ids(theirs) == ["t2"]
    assert mine.json()["total"] == 1
    task = mine.json()["entry"][0]["resource"]
    assert task["status"] == "in-progress"
    assert values(task, "returns-at") == ["2026-10-23T13:19:00Z"]
    assert values(task, "age-band") == ["80+"]


async def test_done_lists_the_requests_the_clinician_advised_newest_first(
    api_client: AsyncClient, world: None, tenant_id: str
) -> None:
    done = await _list(api_client, tenant_id, "completed", CLIN_1)
    other = await _list(api_client, tenant_id, "completed", CLIN_2)

    assert _ids(done) == ["a1"]
    assert _ids(other) == ["a2"]
    task = done.json()["entry"][0]["resource"]
    assert task["status"] == "completed"
    assert values(task, "advice-choice") == ["go-ahead"]
    assert values(task, "advised-at") == ["2026-10-23T13:11:00Z"]
    assert NOTE not in done.text


async def test_a_status_that_is_not_listed_is_a_400(
    api_client: AsyncClient, world: None, tenant_id: str
) -> None:
    response = await _list(api_client, tenant_id, "cancelled")

    assert response.status_code == 400


async def test_the_lists_are_for_a_clinical_advisor_only(
    api_client: AsyncClient, world: None, tenant_id: str
) -> None:
    for role in (Role.ADVISOR, Role.LEAD, Role.EXEC, Role.REPORTER):
        for status in ("in-progress", "completed"):
            response = await api_client.get(
                QUEUE,
                params={"code": "clinical-advice", "status": status},
                headers=_as(tenant_id, role, ADVISOR_1),
            )

            assert response.status_code == 404, (role, status)


async def test_tenant_bs_requests_are_in_neither_of_tenant_as_lists(
    api_client: AsyncClient,
    world: None,
    tenant_id: str,
    other_tenant_id: str,
    uow_factory_b: UnitOfWorkFactory,
) -> None:
    await _people(uow_factory_b, ADVISOR_1, CLIN_1)
    async with uow_factory_b() as uow:
        await uow.cases.add(_case(B_CASE, B_REFERENCE))
        await uow.clinical_requests.add(_request("b-taken", B_CASE, ADVISOR_1, taken_by=CLIN_1))
        await uow.clinical_requests.add(
            _request("b-done", B_CASE, ADVISOR_1, taken_by=CLIN_1, advised=True)
        )
        await uow.commit()

    mine = await _list(api_client, tenant_id, "in-progress", CLIN_1)
    done = await _list(api_client, tenant_id, "completed", CLIN_1)
    b_mine = await _list(api_client, other_tenant_id, "in-progress", CLIN_1)
    b_done = await _list(api_client, other_tenant_id, "completed", CLIN_1)

    assert _ids(mine) == ["t1"]
    assert _ids(done) == ["a1"]
    assert _ids(b_mine) == ["b-taken"]
    assert _ids(b_done) == ["b-done"]


# B3: the clinician reads their own presence.


async def test_a_clinician_reads_their_own_presence_and_the_count_without_a_name(
    api_client: AsyncClient, world: None, tenant_id: str
) -> None:
    headers = _as(tenant_id, Role.CLINICAL, CLIN_1)
    before = await api_client.get("/clinical/presence", headers=headers)
    await api_client.put("/clinical/presence", json={"presence": "busy"}, headers=headers)
    busy = await api_client.get("/clinical/presence", headers=headers)
    await api_client.put("/clinical/presence", json={"presence": "available"}, headers=headers)
    available = await api_client.get("/clinical/presence", headers=headers)

    assert before.json() == {"presence": None, "available": 0}
    assert busy.json() == {"presence": "busy", "available": 0}
    assert available.json() == {"presence": "available", "available": 1}
    for response in (before, busy, available):
        assert CLIN_1 not in response.text


async def test_one_clinicians_presence_is_not_anothers_and_not_the_other_tenants(
    api_client: AsyncClient, world: None, tenant_id: str, other_tenant_id: str
) -> None:
    await api_client.put(
        "/clinical/presence",
        json={"presence": "available"},
        headers=_as(tenant_id, Role.CLINICAL, CLIN_1),
    )

    second = await api_client.get(
        "/clinical/presence", headers=_as(tenant_id, Role.CLINICAL, CLIN_2)
    )
    other_tenant = await api_client.get(
        "/clinical/presence", headers=_as(other_tenant_id, Role.CLINICAL, CLIN_1)
    )

    assert second.json() == {"presence": None, "available": 1}
    assert other_tenant.json() == {"presence": None, "available": 0}
