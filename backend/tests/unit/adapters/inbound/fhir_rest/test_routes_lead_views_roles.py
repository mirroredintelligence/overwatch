"""The role boundary of the shift lead's W7B routes (C): only the shift lead reaches them, and every
other role is the 404 a missing record gets, before a unit of work is opened (DEC-086 item 5). The
platform operator's token is a 401 at the edge (DEC-134)."""

from typing import Any

import pytest

from diucs.domain.codes import Role
from tests.support.w7b_roles import EDGE_REFUSED, headers_for, roles_client

pytestmark = pytest.mark.asyncio(loop_scope="session")

# Method, path, the answer a lead gets before any store is opened (a POST with no key is the
# route's own 400; a read has none, and reaches the double that refuses a store).
ROUTES: list[tuple[str, str, int | None]] = [
    ("GET", "/lead/overview", None),
    ("GET", "/lead/reporters", None),
    ("GET", "/lead/phones", None),
    ("GET", "/lead/invitations", None),
    ("GET", "/lead/services/svc-1/suspension", None),
    ("GET", "/admin/report-flags?status=closed", None),
    ("POST", "/lead/services/svc-1/remind", 400),
    ("POST", "/lead/services/svc-1/test-prompt", 400),
    ("POST", "/lead/invitations/inv-1/resend", 400),
    ("POST", "/lead/invitations/inv-1/switch-to-text", 400),
]


@pytest.mark.parametrize(("method", "path", "answer"), ROUTES)
async def test_each_route_takes_the_lead_and_refuses_every_other_role(
    method: str, path: str, answer: int | None
) -> None:
    async with roles_client() as client:
        for role in Role:
            response: Any = await client.request(
                method, path, content=b"", headers=headers_for(role)
            )
            if role is Role.LEAD:
                assert response.status_code not in (401, 404), (role, response.status_code)
                if answer is not None:
                    assert response.status_code == answer
            elif role in EDGE_REFUSED:
                assert response.status_code == 401, role
            else:
                assert response.status_code == 404, role
