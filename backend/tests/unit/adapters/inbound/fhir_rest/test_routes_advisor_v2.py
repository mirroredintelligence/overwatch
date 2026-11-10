"""The Advisor v2 service routes (DEC-1377): the role boundary of the single-service check and of
the ask, and the refusals that come before any read. The stored answers, the idempotent replay and
the tenant boundary are in tests/integration/. No Neo4j, no network."""

import pytest

from overwatch.application.use_cases.ask_capacity_now import ASK_ROLES
from overwatch.application.use_cases.find_services import FIND_ROLES
from overwatch.domain.codes import Role
from tests.support.route_unit import KEY, assert_role_matrix, bearer, route_client

BODY = {
    "postcode": "DT4 8XX",
    "ageBand": "80+",
    "needs": ["frailty"],
    "urgency": "today",
}


async def test_the_check_is_for_the_advisor_and_advisor_v2_only() -> None:
    async with route_client() as client:
        await assert_role_matrix(
            client,
            "POST",
            "/advisor-v2/services/svc-1/check",
            frozenset(FIND_ROLES),
            body={"postcode": "not a postcode", "ageBand": "80+", "needs": ["frailty"]},
        )


async def test_the_ask_is_for_the_lead_advisor_advisor_v2_and_clinical_only() -> None:
    assert set(ASK_ROLES) == {Role.LEAD, Role.ADVISOR, Role.ADVISOR_V2, Role.CLINICAL}
    async with route_client() as client:
        await assert_role_matrix(
            client,
            "POST",
            "/advisor-v2/services/svc-1/ask",
            frozenset(ASK_ROLES),
            headers={**KEY, "Content-Type": "application/json"},
        )


@pytest.mark.parametrize(
    "role", [Role.REPORTER, Role.WALL, Role.OWNER, Role.EXEC, Role.ANALYTICS_USER]
)
async def test_the_other_roles_get_the_missing_record_404_on_both_routes(role: Role) -> None:
    async with route_client() as client:
        check = await client.post(
            "/advisor-v2/services/svc-1/check", json=BODY, headers=bearer(role)
        )
        ask = await client.post(
            "/advisor-v2/services/svc-1/ask",
            headers={**KEY, **bearer(role), "Content-Type": "application/json"},
        )

    assert (check.status_code, ask.status_code) == (404, 404)


async def test_a_bad_check_body_is_a_400_before_anything_is_read_and_does_not_echo_it() -> None:
    async with route_client() as client:
        bad_postcode = await client.post(
            "/advisor-v2/services/svc-1/check",
            json={**BODY, "needs": ["nonsense"]},
            headers=bearer(Role.ADVISOR_V2),
        )
        no_needs = await client.post(
            "/advisor-v2/services/svc-1/check",
            json={**BODY, "needs": []},
            headers=bearer(Role.ADVISOR_V2),
        )

    assert (bad_postcode.status_code, no_needs.status_code) == (400, 400)
    assert "DT4" not in bad_postcode.text + no_needs.text


async def test_an_ask_without_an_idempotency_key_is_a_400() -> None:
    async with route_client() as client:
        response = await client.post(
            "/advisor-v2/services/svc-1/ask",
            headers={**bearer(Role.ADVISOR), "Content-Type": "application/json"},
        )

    assert response.status_code == 400
