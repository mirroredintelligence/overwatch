"""The role boundary of the clinical routes added in W7A (B1 to B3, B5 to B7): refused before any
read. The stored answers are in tests/integration/adapters/inbound/fhir_rest/.
"""

from diucs.domain.codes import Role
from tests.support.route_unit import assert_role_matrix, route_client

CLINICAL = frozenset({Role.CLINICAL})


async def test_mine_and_done_are_for_the_clinical_advisor_only() -> None:
    async with route_client() as client:
        for status in ("in-progress", "completed"):
            await assert_role_matrix(
                client, "GET", f"/fhir/Task?code=clinical-advice&status={status}", CLINICAL
            )


async def test_a_status_that_is_not_listed_is_a_400_for_the_clinical_advisor() -> None:
    from tests.support.route_unit import bearer

    async with route_client() as client:
        response = await client.get(
            "/fhir/Task?code=clinical-advice&status=cancelled", headers=bearer(Role.CLINICAL)
        )

    assert response.status_code == 400


async def test_a_clinician_reads_their_own_presence_and_no_one_else_does() -> None:
    async with route_client() as client:
        await assert_role_matrix(client, "GET", "/clinical/presence", CLINICAL)
