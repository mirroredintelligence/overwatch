"""The service detail page's read (DEC-1366): GET /clinical/services/{id}/detail, in-process on the
lead world of the test rig. No Neo4j, no network.

The page is for the advisor, Advisor v2 and the Analytics User. It names the service's own number
(a role or switchboard number, DEC-1100) and never a person's email or mobile; what is not held is
null, never made up.
"""

from datetime import date

import pytest

from overwatch.domain.codes import CriteriaStatus, NeedCategory, Role
from overwatch.domain.model.criteria import ServiceCriteria
from tests.support.w7b_rig import LEAD, Rig, bearer, client

pytestmark = pytest.mark.asyncio(loop_scope="session")

URL = "/clinical/services/svc-a/detail"
HISTORY = "/clinical/services/svc-a/history"
KEYS = {
    "serviceId",
    "name",
    "category",
    "status",
    "unitLabel",
    "established",
    "effectiveAvailable",
    "overBy",
    "lastFigure",
    "reportedAt",
    "nextDueAt",
    "cadence",
    "overdue",
    "staleWarning",
    "dataAgeSeconds",
    "phone",
    "openingHours",
    "accepts",
    "excludes",
    "ageMin",
    "ageMax",
    "districts",
}


def _world(*, phone: str | None = "01305 000000", criteria: bool = True) -> Rig:
    rig = Rig()
    rig.lead_world()
    if phone is not None:
        rig.units.services.phones["svc-a"] = phone
    if criteria:
        rig.units.criteria.versions["crit-a"] = ServiceCriteria(
            id="crit-a",
            service_id="svc-a",
            version=3,
            status=CriteriaStatus.CURRENT,
            age_min=18,
            age_max=None,
            districts=frozenset({"DT4", "DT5"}),
            accepts=frozenset({NeedCategory.FRAILTY, NeedCategory.WOUND_CARE}),
            excludes=frozenset({NeedCategory.IV_THERAPY}),
            review_by=date(2027, 1, 15),
            owner_role_id="role-owner",
        )
    return rig


@pytest.mark.parametrize(
    "role", [Role.ADVISOR, Role.ADVISOR_V2, Role.ANALYTICS_USER], ids=lambda role: role.value
)
async def test_each_reader_gets_the_service_and_nothing_else(role: Role) -> None:
    async with client(_world()) as http:
        response = await http.get(URL, headers=bearer(role, "person-1"))

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == KEYS
    assert body["serviceId"] == "svc-a"
    assert body["name"] == "Ward A"
    assert body["category"] == "inpatient-beds"
    assert body["unitLabel"] == "beds"
    assert body["established"] == 10
    assert body["phone"] == "01305 000000"
    assert body["districts"] == ["DT4", "DT5"]
    assert body["accepts"] == ["frailty", "wound-care"]
    assert body["excludes"] == ["iv-therapy"]
    assert body["ageMin"] == 18
    assert body["ageMax"] is None
    assert body["openingHours"] == [
        {"days": [0, 1, 2, 3, 4, 5, 6], "allDay": True, "start": None, "end": None}
    ]


async def test_the_reporting_facts_are_the_boards() -> None:
    async with client(_world()) as http:
        body = (await http.get(URL, headers=bearer(Role.ADVISOR, "advisor-1"))).json()

    # Ward A reported 2 beds at 06:30 and missed its 08:00 prompt (the lead world).
    assert body["lastFigure"] == 2
    assert body["reportedAt"] == "2026-10-30T06:30:00Z"
    assert body["cadence"] == "every-2-hrs"
    assert body["overdue"] is True
    assert body["nextDueAt"] is not None
    assert isinstance(body["dataAgeSeconds"], int)


async def test_no_number_and_no_criteria_are_null_and_empty_never_invented() -> None:
    async with client(_world(phone=None, criteria=False)) as http:
        response = await http.get(URL, headers=bearer(Role.ANALYTICS_USER, "analyst-1"))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["phone"] is None
    assert body["accepts"] is None
    assert body["excludes"] is None
    assert body["districts"] == []
    assert body["ageMin"] is None


async def test_no_email_and_no_mobile_of_a_person_is_in_the_answer() -> None:
    rig = _world()
    rig.units.contacts.phones["work-prac-rep-a"] = "07700 900123"
    async with client(rig) as http:
        text = (await http.get(URL, headers=bearer(Role.ADVISOR, "advisor-1"))).text

    assert "07700" not in text
    assert "@" not in text
    assert "email" not in text.lower()


@pytest.mark.parametrize("role", [Role.LEAD, Role.CLINICAL, Role.REPORTER, Role.EXEC])
async def test_every_other_role_is_refused_as_not_found(role: Role) -> None:
    async with client(_world()) as http:
        response = await http.get(URL, headers=bearer(role, LEAD))
    assert response.status_code == 404


async def test_a_service_that_is_not_there_is_a_404() -> None:
    async with client(_world()) as http:
        response = await http.get(
            "/clinical/services/nope/detail", headers=bearer(Role.ADVISOR, "advisor-1")
        )
    assert response.status_code == 404


async def test_a_suspended_or_inactive_service_is_not_there() -> None:
    rig = _world()
    rig.units.services.profiles["svc-a"] = rig.units.services.profiles["svc-a"].__class__(
        **{**rig.units.services.profiles["svc-a"].__dict__, "active": False}
    )
    async with client(rig) as http:
        response = await http.get(URL, headers=bearer(Role.ADVISOR, "advisor-1"))
    assert response.status_code == 404


@pytest.mark.parametrize("role", [Role.ADVISOR_V2, Role.ANALYTICS_USER], ids=lambda r: r.value)
async def test_the_day_chart_read_is_open_to_both_new_roles(role: Role) -> None:
    async with client(_world()) as http:
        response = await http.get(HISTORY, headers=bearer(role, "person-1"))

    assert response.status_code == 200, response.text
    assert response.json()["points"][0]["available"] == 2
