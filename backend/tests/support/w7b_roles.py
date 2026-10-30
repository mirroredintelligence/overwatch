"""An app whose unit of work fails the test if it is ever opened, for the role-boundary tests of
the W7B routes: a refused role never reaches a store, and a permitted role that is stopped by its
own checks never does either. Test double only."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
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
from tests.support.w7b_rig import NOW

EDGE_REFUSED: frozenset[Role] = frozenset({Role.PLATFORM_OPERATOR})
"""The platform operator has no data access (DEC-134): its token is a 401 on every tenant route."""


@dataclass(frozen=True)
class _Container:
    clock: FixedClock
    ids: SequentialIds
    uow_factory: Any
    secrets: FixedSecretStore
    tenants: Any


def _no_unit_of_work() -> Any:
    raise AssertionError("a route opened a unit of work before it refused")


def headers_for(role: Role, *, content_type: bool = True) -> dict[str, str]:
    token = issue_test_token(role, [], "prac-1")
    headers = {"Authorization": f"Bearer {token}"}
    if content_type:
        headers["Content-Type"] = "application/json"
    return headers


@asynccontextmanager
async def roles_client() -> AsyncIterator[AsyncClient]:
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
