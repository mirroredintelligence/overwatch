"""The subscription, alert and week-summary routes (R12) in-process and with no Neo4j.

Each refusal here is made before a unit of work is opened, against a container whose unit-of-work
factory fails the test if it is called. The stored results (the preferences, the alerts, the
acknowledgement, the snooze, the week figures) are in
tests/integration/adapters/inbound/fhir_rest/test_routes_alerts.py (written, not run in
this build).

A permitted role is checked with a request that has no key, so the answer is the route's own 400,
which an unknown path cannot give. The platform operator has no data access and its token is
refused at the edge with 401 (DEC-134). Sample values only.
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
from diucs.domain.codes import Role, code_system_url
from tests.support.edge import active_tenants

NOW = datetime(2026, 10, 23, 13, 12, tzinfo=UTC)
SUBSCRIPTION = "/fhir/Subscription"
ACK = "/fhir/Task/alert-1/$acknowledge"
SNOOZE = "/fhir/Task/alert-1/$snooze"
ALERTS = "/fhir/Task?code=acknowledge-alert&owner=me"
SUMMARY = "/fhir/HealthcareService/$week-summary"
KEY = {"Idempotency-Key": "alerts-route-key-0001"}
EDGE_REFUSED: frozenset[Role] = frozenset({Role.PLATFORM_OPERATOR})
SUBSCRIBERS = frozenset({Role.EXEC, Role.LEAD})


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


def _bearer(role: Role, sub: str = "prac-lead") -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_test_token(role, [], sub)}"}


def _subscription(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "resourceType": "Subscription",
        "id": "prac-lead",
        "status": "active",
        "reason": "Alert preferences",
        "criteria": "alert-preferences",
        "channel": {"type": "message"},
        "extension": [
            {
                "url": code_system_url("alert-preferences/not-updated-hours"),
                "valueInteger": 4,
            },
            {"url": code_system_url("alert-preferences/ack-minutes"), "valueInteger": 15},
        ],
    }
    body.update(overrides)
    return body


# ---------------------------------------------------------------- the role boundary of each route


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("PUT", f"{SUBSCRIPTION}/prac-lead", _subscription()),
        ("POST", SNOOZE, None),
    ],
)
async def test_each_keyed_route_takes_exec_and_lead_and_refuses_the_rest(
    method: str, path: str, body: dict[str, Any] | None
) -> None:
    async with _client() as client:
        for role in Role:
            headers = {**_bearer(role), "If-Match": 'W/"1"'}
            response = await client.request(
                method,
                path,
                content=b"" if body is None else None,
                json=body,
                headers={**headers, "Content-Type": "application/json"},
            )
            if role in SUBSCRIBERS:
                assert response.status_code == 400, role
                assert response.json()["issue"][0]["code"] == "required", role
            elif role in EDGE_REFUSED:
                assert response.status_code == 401, role
            else:
                assert response.status_code == 404, role


async def test_the_acknowledgement_path_is_shared_by_role_with_the_booking_withdrawal() -> None:
    # The same path is an executive's or a lead's alert acknowledgement and an advisor's booking
    # withdrawal acknowledgement (R17). An executive or a lead gets this route's own key check; an
    # advisor or a clinical advisor gets the booking route's key check, which is the same 400.
    async with _client() as client:
        for role in Role:
            response = await client.post(
                ACK, content=b"", headers={"Content-Type": "application/json", **_bearer(role)}
            )
            if role in SUBSCRIBERS or role in {Role.ADVISOR, Role.CLINICAL}:
                assert response.status_code == 400, role
                assert response.json()["issue"][0]["code"] == "required", role
            elif role in EDGE_REFUSED:
                assert response.status_code == 401, role
            else:
                assert response.status_code == 404, role


async def test_the_subscription_and_alert_reads_and_the_summary_are_for_exec_and_lead() -> None:
    async with _client() as client:
        for path in (SUBSCRIPTION, ALERTS, f"{SUMMARY}?weekStart=2026-10-19"):
            for role in Role:
                response = await client.get(path, headers=_bearer(role))
                if role in SUBSCRIBERS:
                    # A subscriber reaches the store, which is not opened here: anything but the
                    # refusal of a role or an unknown path.
                    assert response.status_code != 404, (path, role)
                elif role in EDGE_REFUSED:
                    assert response.status_code == 401, (path, role)
                else:
                    assert response.status_code == 404, (path, role)


# ----------------------------------------------------------------- refusals that need no store


async def test_another_practitioners_subscription_is_not_found_and_own_is_a_route() -> None:
    # The control: the caller's own subscription without a version is the route's own 428, so a
    # missing route (which also answers 404) cannot make the other practitioner's 404 pass.
    async with _client() as client:
        own = await client.put(
            f"{SUBSCRIPTION}/prac-lead",
            json=_subscription(),
            headers={**KEY, **_bearer(Role.LEAD), "Content-Type": "application/json"},
        )
        other = await client.put(
            f"{SUBSCRIPTION}/prac-someone-else",
            json=_subscription(id="prac-someone-else"),
            headers={**KEY, **_bearer(Role.LEAD), "If-Match": 'W/"1"'},
        )
    assert own.status_code == 428
    assert other.status_code == 404


async def test_a_not_updated_threshold_of_three_hours_is_a_bad_request_naming_the_setting() -> None:
    body = _subscription(
        extension=[
            {"url": code_system_url("alert-preferences/not-updated-hours"), "valueInteger": 3}
        ]
    )
    async with _client() as client:
        response = await client.put(
            f"{SUBSCRIPTION}/prac-lead",
            json=body,
            headers={**KEY, **_bearer(Role.LEAD), "If-Match": 'W/"1"'},
        )
    assert response.status_code == 400
    assert response.json()["issue"][0]["expression"] == ["notUpdatedHours"]


async def test_a_summary_without_a_week_start_is_a_bad_request() -> None:
    async with _client() as client:
        response = await client.get(SUMMARY, headers=_bearer(Role.EXEC))
    assert response.status_code == 400
    assert response.json()["issue"][0]["expression"] == ["weekStart"]


async def test_a_summary_for_a_day_that_is_not_a_monday_is_a_bad_request() -> None:
    async with _client() as client:
        response = await client.get(
            SUMMARY, params={"weekStart": "2026-10-21"}, headers=_bearer(Role.EXEC)
        )
    assert response.status_code == 400
    assert response.json()["issue"][0]["expression"] == ["weekStart"]


async def test_a_summary_for_a_network_is_refused_until_the_network_variant_exists() -> None:
    async with _client() as client:
        response = await client.get(
            SUMMARY,
            params={"weekStart": "2026-10-19", "scope": "network"},
            headers=_bearer(Role.EXEC),
        )
    assert response.status_code == 400
    assert response.json()["issue"][0]["expression"] == ["scope"]


async def test_the_alert_list_names_the_code_and_the_owner_it_accepts() -> None:
    async with _client() as client:
        other_code = await client.get(
            "/fhir/Task",
            params={"code": "booking", "owner": "me"},
            headers=_bearer(Role.LEAD),
        )
        other_owner = await client.get(
            "/fhir/Task",
            params={"code": "acknowledge-alert", "owner": "someone-else"},
            headers=_bearer(Role.LEAD),
        )
    assert other_code.status_code == 400
    assert other_code.json()["issue"][0]["expression"] == ["code"]
    assert other_owner.status_code == 400
    assert other_owner.json()["issue"][0]["expression"] == ["owner"]
