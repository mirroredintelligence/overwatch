"""The Advisor v2 service routes (DEC-1377): the role boundary of the single-service check and of
the ask, and the refusals that come before any read. The stored answers, the idempotent replay and
the tenant boundary are in tests/integration/. No Neo4j, no network."""

from datetime import UTC, datetime

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


def test_the_capacity_answer_counts_out_of_hours_as_a_state_of_its_own() -> None:
    from overwatch.adapters.inbound.fhir_rest.routes_advisor_v2 import _overview_body
    from overwatch.application.use_cases.find_services import capacity_overview
    from overwatch.domain.codes import Status
    from tests.unit.application.use_cases.test_find_services import _entry

    view = capacity_overview(
        (
            _entry(service_id="a", name="A", status=Status.ACCEPTING),
            _entry(service_id="b", name="B", status=Status.OUT_OF_HOURS),
        ),
        generated_at=datetime(2026, 11, 10, 12, 0, tzinfo=UTC),
    )

    counts = _overview_body(view)["counts"]
    assert counts["outOfHours"] == 1
    assert counts["accepting"] == 1
    # Every service is in exactly one count, so the counts add up to the services listed.
    assert sum(counts.values()) == len(view.rows)


def test_each_capacity_row_carries_its_next_due_time_for_the_reopening_line() -> None:
    from datetime import timedelta

    from overwatch.adapters.inbound.fhir_rest.routes_advisor_v2 import _overview_body
    from overwatch.application.use_cases.find_services import capacity_overview
    from overwatch.domain.codes import Status
    from tests.unit.application.use_cases.test_find_services import NOW, _entry

    view = capacity_overview(
        (
            _entry(
                service_id="a",
                name="A",
                status=Status.OUT_OF_HOURS,
                next_due_at=NOW + timedelta(hours=10),
            ),
            _entry(service_id="b", name="B", next_due_at=None),
        ),
        generated_at=NOW,
    )

    rows = {row["serviceId"]: row for row in _overview_body(view)["services"]}
    assert rows["a"]["nextDueAt"] == (NOW + timedelta(hours=10)).isoformat().replace("+00:00", "Z")
    assert rows["b"]["nextDueAt"] is None
