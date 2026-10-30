"""The role boundary of the clinical routes added in W7A (B1 to B3, B5 to B7): refused before any
read. The stored answers are in tests/integration/adapters/inbound/fhir_rest/.
"""

from diucs.domain.codes import Role
from tests.support.route_unit import KEY, assert_role_matrix, bearer, route_client

CLINICAL = frozenset({Role.CLINICAL})


async def test_mine_and_done_are_for_the_clinical_advisor_only() -> None:
    async with route_client() as client:
        for status in ("in-progress", "completed"):
            await assert_role_matrix(
                client, "GET", f"/fhir/Task?code=clinical-advice&status={status}", CLINICAL
            )


async def test_a_status_that_is_not_listed_is_a_400_for_the_clinical_advisor() -> None:
    async with route_client() as client:
        response = await client.get(
            "/fhir/Task?code=clinical-advice&status=cancelled", headers=bearer(Role.CLINICAL)
        )

    assert response.status_code == 400


async def test_a_clinician_reads_their_own_presence_and_no_one_else_does() -> None:
    async with route_client() as client:
        await assert_role_matrix(client, "GET", "/clinical/presence", CLINICAL)


# B4: the problem report (U41) is mounted.

PROBLEM = "/help/problems"
PROBLEM_BODY = {
    "category": "screen-slow",
    "text": "The board took a while.",
    "sessionShared": False,
}
REFUSED_AT_THE_DOOR = frozenset({Role.WALL, Role.ANONYMOUS_LINK})


async def test_a_problem_report_is_for_a_signed_in_person_and_not_a_wall_or_a_link() -> None:
    permitted = frozenset(role for role in Role if role not in REFUSED_AT_THE_DOOR)
    async with route_client() as client:
        await assert_role_matrix(client, "POST", PROBLEM, permitted, body=PROBLEM_BODY, headers=KEY)


async def test_a_problem_report_without_a_key_is_a_400_that_names_the_header() -> None:
    async with route_client() as client:
        response = await client.post(PROBLEM, json=PROBLEM_BODY, headers=bearer(Role.REPORTER))

    assert response.status_code == 400
    assert response.json()["issue"][0]["code"] == "required"


async def test_a_problem_report_that_is_not_valid_is_a_400_and_never_echoes_the_text() -> None:
    long_text = "x" * 281
    async with route_client() as client:
        for body in (
            {"category": "not-a-category", "sessionShared": False},
            {"category": "screen-slow", "text": long_text, "sessionShared": False},
            {"category": "screen-slow", "sessionShared": "yes"},
            {"category": "screen-slow", "unknown": 1},
            {"text": "no category"},
        ):
            response = await client.post(
                PROBLEM, json=body, headers={**KEY, **bearer(Role.REPORTER)}
            )

            assert response.status_code == 400, body
            assert long_text not in response.text


# B5: the state of the person's support code.


async def test_the_support_code_state_is_for_a_named_person_and_not_support() -> None:
    # Support opens sessions; a wall screen and an anonymous link are no one: none shares a session.
    permitted = frozenset(
        role for role in Role if role not in (Role.SUPPORT, Role.WALL, Role.ANONYMOUS_LINK)
    )
    async with route_client() as client:
        await assert_role_matrix(
            client,
            "GET",
            "/support/codes/current?sessionId=a1b2c3d4e5f60718",
            permitted,
        )
