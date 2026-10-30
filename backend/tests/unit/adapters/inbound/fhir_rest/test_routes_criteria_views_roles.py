"""The role boundary of the criteria reads (W7B B): the owner, the clinical lead and the shift lead
reach them; every other role is the 404 a missing record gets, before a unit of work is opened."""

import pytest

from diucs.domain.codes import Role
from tests.support.w7b_roles import EDGE_REFUSED, headers_for, roles_client

pytestmark = pytest.mark.asyncio(loop_scope="session")

PERMITTED = frozenset({Role.OWNER, Role.CLINICAL, Role.LEAD})


@pytest.mark.parametrize("path", ["/criteria/svc-1", "/criteria/svc-1/pending"])
async def test_each_read_takes_its_roles_and_refuses_the_rest(path: str) -> None:
    async with roles_client() as client:
        for role in Role:
            response = await client.get(path, headers=headers_for(role))
            if role in PERMITTED:
                # The route's own checks come after the role; the unit of work then fails the
                # test's double, so the answer is a server error, never a 401 or a 404.
                assert response.status_code not in (401, 404), role
            elif role in EDGE_REFUSED:
                assert response.status_code == 401, role
            else:
                assert response.status_code == 404, role
