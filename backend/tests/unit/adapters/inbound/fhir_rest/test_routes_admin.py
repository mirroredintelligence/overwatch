"""The lead, identity and audit routes (R13) in-process and with no Neo4j: role, key, shape and
refusal checks.

Each refusal here is made before a unit of work or the code store is touched, against a container
whose unit-of-work factory fails the test if it is called. The stored results (the suspension, the
resume, the removal, the move, the flag, the sign-out, the lost phone, the audit replay) are in
tests/integration/adapters/inbound/fhir_rest/test_routes_admin.py, written but not run in this
build. Sample values only: no name, no number that is a real one, no patient data.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
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

NOW = datetime(2026, 10, 23, 13, 12, tzinfo=UTC)
KEY = {"Idempotency-Key": "admin-route-key-0001"}
EDGE_REFUSED: frozenset[Role] = frozenset({Role.PLATFORM_OPERATOR})
LEAD_ONLY = frozenset({Role.LEAD})
SUSPEND = "/fhir/HealthcareService/svc-1/$suspend"
RESUME = "/fhir/HealthcareService/svc-1/$resume"
REMOVE = "/fhir/PractitionerRole/role-1/$remove"
MOVE = "/fhir/HealthcareService/svc-1/$move"
FLAGS = "/admin/report-flags"
RESOLVE = "/admin/report-flags/flag-1/$resolve"
SIGN_OUT = "/identity/sign-out-everywhere"
CONFIRM_PHONE = "/fhir/Practitioner/prac-1/$confirm-new-phone"
AUDIT = "/admin/audit/SC-0192"


@dataclass(frozen=True)
class _RouteContainer:
    clock: FixedClock
    ids: SequentialIds
    uow_factory: Any
    secrets: FixedSecretStore
    tenants: Any


def _no_unit_of_work() -> Any:
    raise AssertionError("the route opened a unit of work before refusing")


@asynccontextmanager
async def _client() -> AsyncIterator[AsyncClient]:
    container = _RouteContainer(
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


def _bearer(role: Role, sub: str = "lead-1") -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_test_token(role, [], sub)}"}


def _parameters(*parts: tuple[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "resourceType": "Parameters",
        "parameter": [{"name": name, **value} for name, value in parts],
    }


async def _send(
    client: AsyncClient, method: str, path: str, body: Any, headers: dict[str, str]
) -> Any:
    """One request. A request with no body still declares a JSON body type, which the app's
    body-type check needs for a POST or PUT (415 otherwise)."""
    if body is None:
        return await client.request(
            method, path, content=b"", headers={**headers, "Content-Type": "application/json"}
        )
    return await client.request(method, path, json=body, headers=headers)


# ----------------------------------------------------------------- the role boundary of each route

_KEYED: list[tuple[str, str, Any, frozenset[Role]]] = [
    ("POST", SUSPEND, _parameters(("reason", {"valueCode": "other"})), LEAD_ONLY),
    (
        "POST",
        RESUME,
        _parameters(
            ("calledBack", {"valueBoolean": True}), ("reasonResolved", {"valueBoolean": True})
        ),
        LEAD_ONLY,
    ),
    ("POST", REMOVE, _parameters(("reason", {"valueCode": "left-service"})), LEAD_ONLY),
    (
        "POST",
        MOVE,
        _parameters(("toMobile", {"valueString": "07700 900123"})),
        LEAD_ONLY,
    ),
    ("POST", RESOLVE, _parameters(("outcome", {"valueCode": "checked"})), LEAD_ONLY),
    ("POST", SIGN_OUT, None, frozenset({Role.REPORTER, Role.LEAD})),
    ("POST", CONFIRM_PHONE, None, LEAD_ONLY),
]


@pytest.mark.parametrize(("method", "path", "body", "permitted"), _KEYED)
async def test_each_keyed_route_takes_its_roles_and_refuses_the_rest(
    method: str, path: str, body: Any, permitted: frozenset[Role]
) -> None:
    async with _client() as client:
        for role in Role:
            response = await _send(client, method, path, body, _bearer(role))
            if role in permitted:
                # No key: the route's own refusal, before any store is touched.
                assert response.status_code == 400, role
                assert response.json()["issue"][0]["code"] == "required", role
            elif role in EDGE_REFUSED:
                assert response.status_code == 401, role
            else:
                assert response.status_code == 404, role


async def test_the_report_flag_list_is_for_the_lead_only() -> None:
    async with _client() as client:
        for role in Role:
            response = await client.get(f"{FLAGS}?status=open", headers=_bearer(role))
            if role is Role.LEAD:
                assert response.status_code != 404, role
            elif role in EDGE_REFUSED:
                assert response.status_code == 401, role
            else:
                assert response.status_code == 404, role


async def test_the_audit_replay_is_for_audit_and_lead_only() -> None:
    permitted = {Role.AUDIT, Role.LEAD}
    async with _client() as client:
        for role in Role:
            response = await client.get(AUDIT, headers=_bearer(role))
            if role in permitted:
                assert response.status_code != 404, role
            elif role in EDGE_REFUSED:
                assert response.status_code == 401, role
            else:
                assert response.status_code == 404, role


# ----------------------------------------------------------------- refusals that need no store


async def test_a_resume_without_the_call_back_is_a_bad_request_naming_it() -> None:
    body = _parameters(
        ("calledBack", {"valueBoolean": False}),
        ("reasonResolved", {"valueBoolean": True}),
    )
    async with _client() as client:
        response = await client.post(RESUME, json=body, headers={**KEY, **_bearer(Role.LEAD)})
    assert response.status_code == 400
    assert response.json()["issue"][0]["expression"] == ["calledBack"]


async def test_a_resume_without_the_resolved_reason_is_a_bad_request_naming_it() -> None:
    body = _parameters(("calledBack", {"valueBoolean": True}))
    async with _client() as client:
        response = await client.post(RESUME, json=body, headers={**KEY, **_bearer(Role.LEAD)})
    assert response.status_code == 400
    assert response.json()["issue"][0]["expression"] == ["reasonResolved"]


async def test_a_suspension_names_a_known_reason() -> None:
    body = _parameters(("reason", {"valueCode": "bored"}))
    async with _client() as client:
        response = await client.post(SUSPEND, json=body, headers={**KEY, **_bearer(Role.LEAD)})
    assert response.status_code == 400
    assert response.json()["issue"][0]["expression"] == ["reason"]


async def test_a_move_to_a_number_that_is_not_a_uk_mobile_is_refused_without_the_number() -> None:
    typed = "0207 946 0000"
    body = _parameters(("toMobile", {"valueString": typed}))
    async with _client() as client:
        response = await client.post(MOVE, json=body, headers={**KEY, **_bearer(Role.LEAD)})
    assert response.status_code == 400
    assert response.json()["issue"][0]["expression"] == ["toMobile"]
    assert typed not in response.text


async def test_a_flag_resolution_names_a_known_outcome() -> None:
    body = _parameters(("outcome", {"valueCode": "dismissed"}))
    async with _client() as client:
        response = await client.post(RESOLVE, json=body, headers={**KEY, **_bearer(Role.LEAD)})
    assert response.status_code == 400
    assert response.json()["issue"][0]["expression"] == ["outcome"]


async def test_the_suspended_outcome_is_not_a_flag_outcome_so_it_is_refused() -> None:
    body = _parameters(("outcome", {"valueCode": "suspended"}))
    async with _client() as client:
        response = await client.post(RESOLVE, json=body, headers={**KEY, **_bearer(Role.LEAD)})
    assert response.status_code == 400
    assert response.json()["issue"][0]["expression"] == ["outcome"]


async def test_the_flag_list_takes_only_open_flags() -> None:
    async with _client() as client:
        response = await client.get(f"{FLAGS}?status=closed", headers=_bearer(Role.LEAD))
    assert response.status_code == 400
    assert response.json()["issue"][0]["expression"] == ["status"]
