"""The role boundary of each W7B registration route (A1, A4): the roles a route takes reach it, and
every other role is refused with the 404 a missing record gets (DEC-086 item 5), before a unit of
work is opened. The platform operator's token is a 401 at the edge (DEC-134). Pure: no store."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from diucs.adapters.inbound.fhir_rest.app import create_app
from diucs.adapters.inbound.fhir_rest.auth import BFF_SECRET_NAME
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.tokens import TEST_BFF_SECRET, default_token_tenant, issue_test_token
from diucs.domain.codes import Role
from tests.support.edge import active_tenants
from tests.support.w7b_rig import NOW

pytestmark = pytest.mark.asyncio(loop_scope="session")

REG = "/registrations/reg-1"
EDGE_REFUSED = frozenset({Role.PLATFORM_OPERATOR})
JSON = {"Content-Type": "application/json"}
EXPLAIN = {
    "resourceType": "Parameters",
    "parameter": [
        {"name": "check", "valueCode": "ods-code"},
        {"name": "note", "valueString": "Phoned."},
    ],
}

# Method, path, body, the roles that may reach it, and the answer a permitted role gets before any
# store is opened (a POST with no key is the route's own 400; a GET that needs a query is a 400).
ROUTES: list[tuple[str, str, dict[str, Any] | None, frozenset[Role], int | None]] = [
    ("GET", f"{REG}/record", None, frozenset({Role.REPORTER}), None),
    ("GET", "/my/registrations", None, frozenset({Role.REPORTER}), None),
    ("GET", f"{REG}/status", None, frozenset({Role.REPORTER}), None),
    ("GET", "/registrations", None, frozenset({Role.LEAD}), None),
    ("GET", f"{REG}/overview", None, frozenset({Role.LEAD}), None),
    ("GET", f"{REG}/decision", None, frozenset({Role.LEAD}), None),
    ("GET", "/addresses", None, frozenset({Role.REPORTER}), 400),
    ("POST", f"{REG}/test-notification", None, frozenset({Role.REPORTER, Role.LEAD}), 400),
    ("POST", f"{REG}/review-request", None, frozenset({Role.REPORTER}), 400),
    ("POST", f"{REG}/confirm-details", None, frozenset({Role.REPORTER}), 400),
    ("POST", "/fhir/Task/reg-1/$start-review", None, frozenset({Role.LEAD}), 400),
    ("POST", "/fhir/Task/reg-1/$explain-check", EXPLAIN, frozenset({Role.LEAD}), 400),
]


@dataclass(frozen=True)
class _Container:
    clock: FixedClock
    ids: SequentialIds
    uow_factory: Any
    secrets: FixedSecretStore
    tenants: Any


def _no_unit_of_work() -> Any:
    raise AssertionError("the route opened a unit of work before refusing")


@asynccontextmanager
async def _client() -> AsyncIterator[AsyncClient]:
    container = _Container(
        clock=FixedClock(NOW),
        ids=SequentialIds(),
        uow_factory=_no_unit_of_work,
        secrets=FixedSecretStore({BFF_SECRET_NAME: TEST_BFF_SECRET}),
        tenants=active_tenants(default_token_tenant()),
    )
    app: FastAPI = create_app(container)  # type: ignore[arg-type]
    app.state.secrets = FixedSecretStore({BFF_SECRET_NAME: TEST_BFF_SECRET})
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        yield client


@pytest.mark.parametrize(("method", "path", "body", "permitted", "answer"), ROUTES)
async def test_each_route_takes_its_roles_and_refuses_the_rest(
    method: str,
    path: str,
    body: dict[str, Any] | None,
    permitted: frozenset[Role],
    answer: int | None,
) -> None:
    async with _client() as client:
        for role in Role:
            token = issue_test_token(role, [], "prac-1")
            headers = {"Authorization": f"Bearer {token}", **JSON}
            if body is None:
                response = await client.request(method, path, content=b"", headers=headers)
            else:
                response = await client.request(method, path, json=body, headers=headers)
            if role in permitted:
                assert response.status_code not in (401, 404), (role, response.status_code)
                if answer is not None:
                    assert response.status_code == answer, role
            elif role in EDGE_REFUSED:
                assert response.status_code == 401, role
            else:
                assert response.status_code == 404, role


@pytest.mark.parametrize(("method", "path", "body", "permitted", "answer"), ROUTES)
async def test_a_request_with_no_token_is_a_401(
    method: str,
    path: str,
    body: dict[str, Any] | None,
    permitted: frozenset[Role],
    answer: int | None,
) -> None:
    async with _client() as client:
        response = await client.request(method, path, content=b"", headers=JSON)
    assert response.status_code == 401
