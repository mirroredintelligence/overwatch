"""An in-process app for the role-matrix tests of the routes (W7A): no Neo4j, no network.

The container's unit-of-work factory fails the test if it is called, so a route that is refused by
its role is shown to be refused before anything is read. A permitted role reaches the use case,
whose unit of work then fails (a 500 here): a test asserts only that the answer is not the refusal.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

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

NOW = datetime(2026, 10, 23, 13, 12, tzinfo=UTC)
KEY = {"Idempotency-Key": "w7a-route-key-0001"}
EDGE_REFUSED: frozenset[Role] = frozenset({Role.PLATFORM_OPERATOR})


@dataclass(frozen=True)
class RouteContainer:
    clock: FixedClock
    ids: SequentialIds
    uow_factory: Any
    secrets: FixedSecretStore
    tenants: Any


def no_unit_of_work() -> Any:
    raise AssertionError("the route opened a unit of work before refusing")


@asynccontextmanager
async def route_client() -> AsyncIterator[AsyncClient]:
    container = RouteContainer(
        clock=FixedClock(NOW),
        ids=SequentialIds(),
        uow_factory=no_unit_of_work,
        secrets=FixedSecretStore({BFF_SECRET_NAME: TEST_BFF_SECRET}),
        tenants=active_tenants(default_token_tenant()),
    )
    app: FastAPI = create_app(container)  # type: ignore[arg-type]
    app.state.secrets = FixedSecretStore({BFF_SECRET_NAME: TEST_BFF_SECRET})
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        yield client


def bearer(role: Role, sub: str = "prac-1") -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_test_token(role, [], sub)}"}


async def assert_role_matrix(
    client: AsyncClient,
    method: str,
    path: str,
    permitted: frozenset[Role],
    *,
    body: Any = None,
    headers: dict[str, str] | None = None,
) -> None:
    """Each permitted role is not refused; the platform operator is refused at the edge (401);
    every other role gets the non-revealing 404."""
    for role in Role:
        sent = {**(headers or {}), **bearer(role)}
        response = await client.request(method, path, json=body, headers=sent)
        if role in permitted:
            assert response.status_code != 404, (path, role)
        elif role in EDGE_REFUSED:
            assert response.status_code == 401, (path, role)
        else:
            assert response.status_code == 404, (path, role)
