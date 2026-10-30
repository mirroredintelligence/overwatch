"""The criteria routes (R10) in-process and with no Neo4j: role, key, review period and note.

Each refusal here is made before a unit of work is opened, against a container whose unit-of-work
factory fails the test if it is called. The stored versions (create, approve, send back, confirm,
history) are in tests/integration/adapters/inbound/fhir_rest/test_routes_criteria.py, written but
not run in this build. Sample values only.
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

pytestmark = pytest.mark.asyncio(loop_scope="session")

NOW = datetime(2026, 10, 23, 13, 12, tzinfo=UTC)
CREATE = "/fhir/Basic"
HISTORY = "/fhir/Basic?subject=HealthcareService/svc-1"
SUBMIT = "/fhir/Basic/basic-1/$submit-for-approval"
APPROVE = "/fhir/Basic/basic-1/$approve"
SEND_BACK = "/fhir/Basic/basic-1/$send-back"
CONFIRM = "/fhir/HealthcareService/svc-1/$confirm-criteria"
EDGE_REFUSED: frozenset[Role] = frozenset({Role.PLATFORM_OPERATOR})
"""A role the token edge refuses on every FHIR route: the platform operator runs tenant lifecycle
only and has no data access (DEC-134), so its token is a 401 before any route is reached."""
KEY = {"Idempotency-Key": "criteria-route-key-0001"}
NOTE_LIMIT = 280
OWNER_ROLES = frozenset({Role.OWNER})


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


def _bearer(role: Role, sub: str = "owner-1") -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_test_token(role, [], sub)}"}


def _parameters(*parts: tuple[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "resourceType": "Parameters",
        "parameter": [{"name": name, **value} for name, value in parts],
    }


def _change_body(**overrides: dict[str, Any]) -> dict[str, Any]:
    parts: dict[str, dict[str, Any]] = {
        "service": {"valueString": "svc-1"},
        "ageMin": {"valueInteger": 18},
        "accepts": {"valueCode": "frailty"},
        "district": {"valueString": "DT4"},
        "changeReason": {"valueString": "Age range widened"},
        "reviewMonths": {"valueInteger": 6},
    }
    parts.update(overrides)
    return _parameters(*((name, value) for name, value in parts.items()))


def _confirm_body(months: dict[str, Any] | None) -> dict[str, Any]:
    parts: list[tuple[str, dict[str, Any]]] = []
    if months is not None:
        parts.append(("reviewInMonths", months))
    return _parameters(*parts)


async def _send(
    client: AsyncClient, method: str, path: str, body: Any, headers: dict[str, str]
) -> Any:
    """One request. A request with no body still declares a JSON body type: the body-type check
    of the app refuses a POST or PUT with no media type before any route runs (415)."""
    if body is None:
        return await client.request(
            method, path, content=b"", headers={**headers, "Content-Type": "application/json"}
        )
    return await client.request(method, path, json=body, headers=headers)


# ----------------------------------------------------------------- the role boundary of each route

_KEYED_ROUTES: list[tuple[str, str, dict[str, Any] | None, frozenset[Role]]] = [
    ("POST", CREATE, _change_body(), OWNER_ROLES),
    ("POST", SUBMIT, None, OWNER_ROLES),
    ("POST", APPROVE, None, frozenset({Role.LEAD})),
    (
        "POST",
        SEND_BACK,
        _parameters(("note", {"valueString": "Please narrow the district."})),
        frozenset({Role.LEAD}),
    ),
    (
        "POST",
        CONFIRM,
        _confirm_body({"valueInteger": 6}),
        frozenset({Role.OWNER, Role.LEAD}),
    ),
]


@pytest.mark.parametrize(("method", "path", "body", "permitted"), _KEYED_ROUTES)
async def test_each_keyed_criteria_route_takes_its_roles_and_refuses_the_rest(
    method: str, path: str, body: dict[str, Any] | None, permitted: frozenset[Role]
) -> None:
    async with _client() as client:
        for role in Role:
            response = await _send(client, method, path, body, _bearer(role))
            if role in permitted:
                assert response.status_code == 400, role
                assert response.json()["issue"][0]["code"] == "required", role
            elif role in EDGE_REFUSED:
                assert response.status_code == 401, role
            else:
                assert response.status_code == 404, role


async def test_the_history_is_for_the_owner_advisor_clinical_and_lead_only() -> None:
    # The advisor reads it for the criteria dialog (W7A-A7, DEC-771).
    permitted = {Role.OWNER, Role.ADVISOR, Role.CLINICAL, Role.LEAD}
    async with _client() as client:
        for role in Role:
            response = await client.get(
                "/fhir/Basic", params={"subject": "HealthcareService/svc-1"}, headers=_bearer(role)
            )
            if role in permitted:
                # A permitted role reaches the store, which this test does not open: anything but
                # the not-found of a refused role or an unknown path.
                assert response.status_code != 404, role
            elif role in EDGE_REFUSED:
                assert response.status_code == 401, role
            else:
                assert response.status_code == 404, role


# ---------------------------------------------------------------- refusals that need no store


async def test_a_review_period_of_five_months_is_refused() -> None:
    async with _client() as client:
        response = await client.post(
            CONFIRM,
            json=_confirm_body({"valueInteger": 5}),
            headers={**KEY, **_bearer(Role.OWNER)},
        )
    assert response.status_code == 400
    assert response.json()["issue"][0]["expression"] == ["reviewInMonths"]


async def test_a_confirmation_without_a_review_period_is_refused() -> None:
    async with _client() as client:
        response = await client.post(
            CONFIRM, json=_confirm_body(None), headers={**KEY, **_bearer(Role.OWNER)}
        )
    assert response.status_code == 400
    assert response.json()["issue"][0]["expression"] == ["reviewInMonths"]


@pytest.mark.parametrize("months", [3, 6, 12])
async def test_the_three_review_periods_pass_the_check(months: int) -> None:
    # These pass the shape check, so the request reaches the store. The store is not opened here,
    # so the answer is its failure: anything but the route's own refusal (400) or an unknown path.
    async with _client() as client:
        response = await client.post(
            CONFIRM,
            json=_confirm_body({"valueInteger": months}),
            headers={**KEY, **_bearer(Role.OWNER)},
        )
    assert response.status_code not in (400, 404)


async def test_a_history_without_a_subject_is_refused() -> None:
    async with _client() as client:
        response = await client.get("/fhir/Basic", headers=_bearer(Role.OWNER))
    assert response.status_code == 400
    assert response.json()["issue"][0]["expression"] == ["subject"]


async def test_a_send_back_note_over_280_characters_is_refused() -> None:
    too_long = "x" * (NOTE_LIMIT + 1)
    body = _parameters(("note", {"valueString": too_long}))
    async with _client() as client:
        response = await client.post(SEND_BACK, json=body, headers={**KEY, **_bearer(Role.LEAD)})
    assert response.status_code == 400
    assert response.json()["issue"][0]["expression"] == ["note"]
    assert too_long not in response.text


async def test_a_criteria_change_without_a_review_period_is_refused() -> None:
    body = _change_body()
    body["parameter"] = [p for p in body["parameter"] if p["name"] != "reviewMonths"]
    async with _client() as client:
        response = await client.post(CREATE, json=body, headers={**KEY, **_bearer(Role.OWNER)})
    assert response.status_code == 400
    assert response.json()["issue"][0]["expression"] == ["reviewMonths"]
