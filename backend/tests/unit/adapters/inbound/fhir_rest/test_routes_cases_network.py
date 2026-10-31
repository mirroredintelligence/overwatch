"""The `network` part of `$filter-options` (KI-349): the network variant of the advisor's options.

The route decides nothing: it checks the shape of the network id, lets the token's claim route,
then runs one use case. A network outside the claim, a role that is not an advisor or a clinician
and a network id that is not one are refused before anything is read; a process with no network
options configured fails closed with a 500, never an empty list. The stored answers are in
tests/integration/application/test_filter_network_options.py.
"""

from typing import Any

import pytest

from diucs.adapters.testing.tokens import issue_test_token
from diucs.domain.codes import Role
from tests.support.route_unit import EDGE_REFUSED, KEY, bearer, route_client

NET = "net-sample-1"
CASE_ROLES = frozenset({Role.ADVISOR, Role.CLINICAL})
PATH = "/fhir/HealthcareService/$filter-options"


def body(network: Any) -> dict[str, Any]:
    return {
        "resourceType": "Parameters",
        "parameter": [
            {"name": "case", "valueReference": {"reference": "ServiceRequest/case-1"}},
            {"name": "network", "valueString": network},
        ],
    }


async def test_the_network_variant_is_for_an_advisor_or_a_clinical_advisor() -> None:
    # The token lists the network, so a permitted role gets past the claim to the use case: no
    # network options are configured here, so it is a 500, never an empty list. Any other role is
    # the one 404 (the platform operator is refused at the edge, 401).
    async with route_client() as client:
        for role in Role:
            token = issue_test_token(role, [], "prac-1", networks=[NET])
            response = await client.post(
                PATH, json=body(NET), headers={**KEY, "Authorization": f"Bearer {token}"}
            )
            if role in CASE_ROLES:
                assert response.status_code == 500, role
            elif role in EDGE_REFUSED:
                assert response.status_code == 401, role
            else:
                assert response.status_code == 404, role


@pytest.mark.parametrize(
    "network", ["", "NET-1", "net-", "net-UPPER", "../x", "net-" + "a" * 40, 7]
)
async def test_a_network_id_of_the_wrong_shape_is_a_400_before_anything_is_read(
    network: Any,
) -> None:
    async with route_client() as client:
        response = await client.post(
            PATH, json=body(network), headers={**KEY, **bearer(Role.ADVISOR)}
        )

    assert response.status_code == 400


async def test_a_network_the_token_does_not_list_is_the_one_404_and_nothing_is_read() -> None:
    async with route_client() as client:
        response = await client.post(PATH, json=body(NET), headers={**KEY, **bearer(Role.ADVISOR)})

    assert response.status_code == 404
    assert response.json()["issue"][0]["code"] == "not-found"
