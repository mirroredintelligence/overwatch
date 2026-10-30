"""The role boundary of the advisor case routes added in W7A (A1, A7, A8): refused before any read.

The stored answers are in tests/integration/adapters/inbound/fhir_rest/test_routes_cases_w7a.py.
"""

from diucs.domain.codes import Role
from tests.support.route_unit import KEY, assert_role_matrix, route_client

CASE_ROLES = frozenset({Role.ADVISOR, Role.CLINICAL})


async def test_reading_a_case_is_for_an_advisor_or_a_clinical_advisor() -> None:
    async with route_client() as client:
        await assert_role_matrix(client, "GET", "/fhir/ServiceRequest/case-1", CASE_ROLES)


async def test_closing_a_case_is_for_an_advisor_or_a_clinical_advisor() -> None:
    parameters = {
        "resourceType": "Parameters",
        "parameter": [{"name": "outcome", "valueCode": "declined"}],
    }
    async with route_client() as client:
        await assert_role_matrix(
            client,
            "POST",
            "/fhir/ServiceRequest/case-1/$close",
            CASE_ROLES,
            body=parameters,
            headers=KEY,
        )
