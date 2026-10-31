"""The coverage routes (DEC-1305): the role boundary, the refusals that come before any read, and
the shape of the answers the front end parses (frontend/lib/areas/types.ts). The stored answers and
the tenant boundary are in tests/integration/.
"""

import pytest

from overwatch.adapters.inbound.fhir_rest.routes_coverage import (
    service_json,
    setting_body,
    window_json,
)
from overwatch.application.use_cases.coverage import (
    CoverageByWindow,
    OtherCover,
    ServiceCoverageView,
    Uncovered,
)
from overwatch.domain.codes import Role
from overwatch.domain.errors import ValidationFailed
from overwatch.domain.rules.coverage_windows import DistrictCover
from tests.support.route_unit import KEY, assert_role_matrix, bearer, route_client

GOOD = {"districts": ["DT3", "DT4"], "responseHours": 2, "days": ["mon", "tue"]}


async def test_the_window_read_is_for_a_lead_or_an_executive_only() -> None:
    async with route_client() as client:
        await assert_role_matrix(
            client, "GET", "/planning/coverage?window=night", frozenset({Role.LEAD, Role.EXEC})
        )


async def test_the_service_read_and_save_are_for_the_lead_only() -> None:
    async with route_client() as client:
        await assert_role_matrix(
            client, "GET", "/lead/services/svc-1/coverage", frozenset({Role.LEAD})
        )
        await assert_role_matrix(
            client,
            "PUT",
            "/lead/services/svc-1/coverage",
            frozenset({Role.LEAD}),
            body=GOOD,
            headers=KEY,
        )


async def test_a_part_of_the_day_that_is_not_listed_is_a_400_that_names_it() -> None:
    async with route_client() as client:
        response = await client.get("/planning/coverage?window=dawn", headers=bearer(Role.LEAD))

    assert response.status_code == 400
    assert "window" in response.text


async def test_a_save_without_an_idempotency_key_is_a_400() -> None:
    async with route_client() as client:
        response = await client.put(
            "/lead/services/svc-1/coverage", json=GOOD, headers=bearer(Role.LEAD)
        )

    assert response.status_code == 400


@pytest.mark.parametrize(
    "content",
    [b"not json", b"[1]", b'{"districts": ["DT3"], "responseHours": 2, "days": ["mon"], "x": 1}'],
)
async def test_a_body_that_is_not_the_three_answers_is_a_400_before_anything_is_read(
    content: bytes,
) -> None:
    async with route_client() as client:
        response = await client.put(
            "/lead/services/svc-1/coverage",
            content=content,
            headers={**bearer(Role.LEAD), **KEY, "Content-Type": "application/json"},
        )

    assert response.status_code == 400


def test_the_body_keeps_only_the_three_answers() -> None:
    assert setting_body(b'{"districts": ["DT3"], "responseHours": 2}') == {
        "districts": ["DT3"],
        "responseHours": 2,
    }
    with pytest.raises(ValidationFailed):
        setting_body(b'{"service": "other"}')


def test_the_window_answer_has_the_shape_the_screen_reads() -> None:
    body = window_json(
        CoverageByWindow(
            window="night",
            districts=(DistrictCover("DT1", ()), DistrictCover("DT3", ("UCR East",))),
            uncovered=Uncovered(None, True, 90),
        )
    )

    assert body == {
        "window": "night",
        "districts": [
            {"district": "DT1", "services": []},
            {"district": "DT3", "services": ["UCR East"]},
        ],
        "uncovered": {"count": None, "suppressed": True, "days": 90},
    }


def test_the_service_answer_has_the_shape_the_screen_reads() -> None:
    body = service_json(
        ServiceCoverageView(
            service_id="svc-1",
            service_name="UCR West",
            available=("DT3", "DT4"),
            others=(OtherCover("DT4", "UCR East"),),
            districts=("DT3",),
            response_hours=None,
            days=("mon",),
        )
    )

    assert body == {
        "service": {"id": "svc-1", "name": "UCR West"},
        "available": ["DT3", "DT4"],
        "others": [{"district": "DT4", "service": "UCR East"}],
        "districts": ["DT3"],
        "responseHours": None,
        "days": ["mon"],
    }
