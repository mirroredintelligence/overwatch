"""GET /analytics/overview (DEC-1368): the Analytics User's one read.

Only that role reaches it; every other role is the 404 a missing record gets, before a unit of work
is opened (DEC-086 item 5), and the platform operator's token is a 401 at the edge (DEC-134). The
answer holds figures only."""

from typing import Any

import pytest

from overwatch.adapters.testing.fixed_geo import FixedPostcodeLocator
from overwatch.application.ports.outbound.geo import LatLon
from overwatch.domain.codes import Role
from overwatch.domain.rules.areas import parse_area_table
from tests.support.w7b_rig import Rig, bearer, client
from tests.support.w7b_roles import EDGE_REFUSED, headers_for, roles_client

pytestmark = pytest.mark.asyncio(loop_scope="session")

FORBIDDEN_WORDS = ("postcode", "patient", "phone", "mobile", "outcome", "nhs")


async def test_each_role_but_the_analytics_user_is_refused() -> None:
    async with roles_client() as http:
        for role in Role:
            response: Any = await http.get("/analytics/overview", headers=headers_for(role))
            if role is Role.ANALYTICS_USER:
                assert response.status_code not in (401, 404), role
            elif role in EDGE_REFUSED:
                assert response.status_code == 401, role
            else:
                assert response.status_code == 404, role


class _Positions:
    async def coverage_districts(self, ids: Any) -> dict[str, tuple[str, ...]]:
        return {"svc-a": ("BH2", "BH1")}

    async def get_many(self, ids: Any) -> dict[str, LatLon]:
        return {"svc-b": LatLon(50.73, -1.86)}  # a site next to the point of BH1


async def test_the_overview_is_figures_only_with_districts_and_the_lists() -> None:
    rig = Rig()
    rig.lead_world()
    rig.units.positions = _Positions()  # type: ignore[attr-defined]
    async with client(rig) as http:
        response = await http.get(
            "/analytics/overview", headers=bearer(Role.ANALYTICS_USER, "prac-an")
        )

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert set(body) == {
        "generatedAt",
        "counts",
        "outOfHours",
        "areas",
        "services",
        "underPressure",
        "underutilised",
    }
    assert set(body["counts"]) == {
        "accepting",
        "limited",
        "notAccepting",
        "overCapacity",
        "notUpdated",
    }
    by_id = {row["serviceId"]: row for row in body["services"]}
    assert by_id["svc-a"]["districts"] == ["BH1", "BH2"]
    assert by_id["svc-b"]["districts"] == []
    assert set(by_id["svc-a"]) == {
        "serviceId",
        "name",
        "category",
        "status",
        "districts",
        "area",
        "figureCurrent",
        "available",
        "overBy",
        "unitLabel",
        "reportedAt",
    }
    # "inpatient-beds" is a service category, not a patient.
    text = response.text.lower().replace("inpatient", "")
    assert [word for word in FORBIDDEN_WORDS if word in text] == []


async def test_with_an_area_table_each_service_is_placed_and_the_areas_are_listed() -> None:
    rig = Rig()
    rig.lead_world()
    rig.units.positions = _Positions()  # type: ignore[attr-defined]
    rig.areas = parse_area_table(  # type: ignore[attr-defined]
        {
            "name": "Test",
            "areas": [{"id": "coast", "name": "Coast", "places": "A · B"}],
            "network": {"id": "network", "name": "Everywhere", "places": "Across areas"},
            "districts": {"BH1": "coast", "BH2": "coast"},
        }
    )
    rig.postcodes = FixedPostcodeLocator({}, {"BH1": LatLon(50.7279, -1.8636)})  # type: ignore[attr-defined]
    async with client(rig) as http:
        response = await http.get(
            "/analytics/overview", headers=bearer(Role.ANALYTICS_USER, "prac-an")
        )

    body = response.json()
    assert body["areas"] == [
        {"id": "coast", "name": "Coast", "places": "A · B"},
        {"id": "network", "name": "Everywhere", "places": "Across areas"},
    ]
    by_id = {row["serviceId"]: row for row in body["services"]}
    assert by_id["svc-a"]["area"] == "coast"  # it covers BH1 and BH2, both in the area
    assert by_id["svc-b"]["area"] == "coast"  # it covers none: placed by its site
