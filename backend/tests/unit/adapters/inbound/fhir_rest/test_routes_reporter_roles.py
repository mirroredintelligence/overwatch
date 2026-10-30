"""The role boundary of the reporter app's routes, for all thirteen roles (W9H, DEC-1040, DEC-1043).

Only a reporter reaches the reporter app. The one exception is the executive's test notification:
an executive holds no post, so every route that reads or writes a post stays closed to them, and
`POST /reporter/push-test` takes them because the notification is the one part of the app an
executive uses (DEC-1040). Every other role is the 404 a missing record gets, and every refusal is
the same body, so a refused role learns nothing about which routes exist (DEC-086 item 5). The
platform operator's token is a 401 at the edge (DEC-134). The app opens no unit of work before it
has refused, so a refused role never reaches a store.
"""

from typing import Any

import pytest

from diucs.domain.codes import Role
from tests.support.w7b_roles import EDGE_REFUSED, headers_for, roles_client

pytestmark = pytest.mark.asyncio(loop_scope="session")

SERVICE = "svc-1"
EXEC_ROUTES = frozenset({("POST", "/reporter/push-test")})

ROUTES: list[tuple[str, str, dict[str, Any] | None]] = [
    ("GET", "/reporter/services", None),
    ("GET", f"/reporter/services/{SERVICE}/prompt", None),
    ("GET", f"/reporter/services/{SERVICE}/history", None),
    ("POST", f"/reporter/services/{SERVICE}/report", {"kind": "confirm"}),
    ("POST", "/reporter/reports/batch", {"items": [{"serviceId": SERVICE, "kind": "confirm"}]}),
    ("GET", "/reporter/settings", None),
    ("POST", "/reporter/cover", {"phone": "07700 900123"}),
    ("POST", "/reporter/channel", {"channel": "text"}),
    ("POST", f"/reporter/services/{SERVICE}/cover", {"phone": "07700 900123"}),
    ("POST", f"/reporter/services/{SERVICE}/accept", {"accept": True}),
    ("GET", "/reporter/setup-summary", None),
    ("POST", "/reporter/push-test", {}),
    ("GET", "/reporter/bookings/1001", None),
    ("POST", "/reporter/bookings/1001/respond", {"decision": "confirm"}),
]


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
async def test_each_route_takes_its_roles_and_refuses_every_other_one_the_same_way(
    method: str, path: str, body: dict[str, Any] | None
) -> None:
    admitted = {Role.REPORTER} | ({Role.EXEC} if (method, path) in EXEC_ROUTES else set())
    refusals: dict[Role, bytes] = {}
    async with roles_client() as client:
        for role in Role:
            response: Any = await client.request(
                method,
                path,
                json=body,
                headers={**headers_for(role), "Idempotency-Key": "reporter-key-0001"},
            )
            if role in admitted:
                # Past the role gate: the route goes on to the person check, which needs a store;
                # the double refuses one, so the answer is not a refusal of the role.
                assert response.status_code not in (401, 404), (role, response.status_code)
            elif role in EDGE_REFUSED:
                assert response.status_code == 401, role
            else:
                assert response.status_code == 404, role
                refusals[role] = response.content

    assert len(set(refusals.values())) == 1, "every refused role gets the same body"
    assert set(refusals) == set(Role) - admitted - EDGE_REFUSED


def test_there_are_thirteen_roles_and_the_matrix_covers_every_one() -> None:
    assert len(list(Role)) == 13
