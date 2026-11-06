"""The day chart's read (DEC-1343): GET /clinical/services/{id}/history, in-process on the lead
world of the test rig. No Neo4j, no network."""

import pytest

from overwatch.domain.codes import Role
from tests.support.w7b_rig import LEAD, Rig, bearer, client

pytestmark = pytest.mark.asyncio(loop_scope="session")

ADVISOR_AUTH = bearer(Role.ADVISOR, "advisor-1")
LEAD_AUTH = bearer(Role.LEAD, LEAD)
REPORTER_AUTH = bearer(Role.REPORTER, "reporter-1")


def _world() -> Rig:
    rig = Rig()
    rig.lead_world()
    return rig


async def test_a_service_gives_what_it_reported_with_the_stale_limit_and_its_unit() -> None:
    async with client(_world()) as http:
        response = await http.get("/clinical/services/svc-a/history", headers=ADVISOR_AUTH)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["unitLabel"] == "beds"
    assert body["staleAfterSeconds"] == 7200
    assert body["points"] == [
        {"at": "2026-10-30T06:30:00Z", "available": 2, "overBy": None, "status": "limited"}
    ]
    assert set(body) == {
        "unitLabel",
        "established",
        "since",
        "until",
        "staleAfterSeconds",
        "points",
    }


async def test_the_shift_lead_reads_it_too() -> None:
    async with client(_world()) as http:
        response = await http.get("/clinical/services/svc-a/history", headers=LEAD_AUTH)
    assert response.status_code == 200


async def test_a_service_that_is_not_there_is_a_404() -> None:
    async with client(_world()) as http:
        response = await http.get("/clinical/services/nope/history", headers=ADVISOR_AUTH)
    assert response.status_code == 404


async def test_a_reporter_cannot_read_it() -> None:
    async with client(_world()) as http:
        response = await http.get("/clinical/services/svc-a/history", headers=REPORTER_AUTH)
    assert response.status_code == 404


async def test_an_hours_value_that_is_not_a_number_is_ignored() -> None:
    async with client(_world()) as http:
        response = await http.get(
            "/clinical/services/svc-a/history?hours=abc", headers=ADVISOR_AUTH
        )
    assert response.status_code == 200
