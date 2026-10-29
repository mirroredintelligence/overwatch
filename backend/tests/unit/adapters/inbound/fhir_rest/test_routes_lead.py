"""The shift lead routes (R08) in-process and with no Neo4j: role, key, channel and number refusals.

The app runs on a container of fixed parts whose unit-of-work factory must never be called: every
case here is refused before a store is touched. The stored results are in the Neo4j-backed route
tests (tests/integration/adapters/inbound/fhir_rest/test_routes_lead.py). Sample values only: the
numbers are the prompt's examples, and the names are not patient data.
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
from diucs.adapters.inbound.fhir_rest.routes_lead import number_ending
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.tokens import TEST_BFF_SECRET, issue_test_token
from diucs.application.ports.outbound.identity import PHONE_HASH_SECRET
from diucs.domain.codes import Role

pytestmark = pytest.mark.asyncio(loop_scope="session")

NOW = datetime(2026, 10, 23, 13, 12, tzinfo=UTC)
SETUP = "/fhir/HealthcareService/$setup"
CHANGE = "/fhir/PractitionerRole/role-1/$change-number"
KEY = {"Idempotency-Key": "lead-setup-key-0001"}
EXAMPLE = "07700 900123"
REFUSAL = "Enter a UK mobile number, for example 07700 900123"


@dataclass(frozen=True)
class _RouteContainer:
    clock: FixedClock
    ids: SequentialIds
    uow_factory: Any
    secrets: FixedSecretStore


def _no_unit_of_work() -> Any:
    raise AssertionError("the route opened a unit of work before refusing")


@asynccontextmanager
async def _client() -> AsyncIterator[AsyncClient]:
    container = _RouteContainer(
        clock=FixedClock(NOW),
        ids=SequentialIds(),
        uow_factory=_no_unit_of_work,
        secrets=FixedSecretStore(
            {BFF_SECRET_NAME: TEST_BFF_SECRET, PHONE_HASH_SECRET: b"phone-test-secret-0123456789ab"}
        ),
    )
    app: FastAPI = create_app(container)
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


def _setup_body(**overrides: Any) -> dict[str, Any]:
    parts: dict[str, tuple[str, dict[str, Any]]] = {
        "name": ("name", {"valueString": "UCR West"}),
        "category": ("category", {"valueCode": "urgent-community-response"}),
        "measure": ("measure", {"valueCode": "referrals-acceptable"}),
        "unitLabel": ("unitLabel", {"valueString": "referrals in the next 2 hrs"}),
        "establishedCapacity": ("establishedCapacity", {"valueInteger": 8}),
        "usualMin": ("usualMin", {"valueInteger": 0}),
        "usualMax": ("usualMax", {"valueInteger": 8}),
        "cadence": ("cadence", {"valueCode": "every-2-hrs"}),
        "channel": ("channel", {"valueCode": "text"}),
        "mobile": ("mobile", {"valueString": EXAMPLE}),
        "roleName": ("roleName", {"valueString": "Duty manager"}),
        "ageMin": ("ageMin", {"valueInteger": 18}),
        "district": ("district", {"valueString": "DT4"}),
        "reviewBy": ("reviewBy", {"valueDate": "2026-12-12"}),
    }
    for key, value in overrides.items():
        parts[key] = (key, value)  # value is the typed value dict, for example {"valueCode": "x"}
    return _parameters(*parts.values())


def _change_body(mobile: str = "07700 900456", duration: str = "today") -> dict[str, Any]:
    return _parameters(("mobile", {"valueString": mobile}), ("duration", {"valueCode": duration}))


async def test_the_set_up_route_exists_for_the_lead() -> None:
    # Guards the two advisor refusals below: an unknown path answers 404 too, so the route must be
    # there for their 404 to mean the role was refused.
    async with _client() as client:
        response = await client.post(SETUP, json=_setup_body(), headers=_bearer(Role.LEAD))
    assert response.status_code == 400
    assert response.json()["resourceType"] == "OperationOutcome"


async def test_an_advisor_is_not_found_for_set_up_and_nothing_is_opened() -> None:
    async with _client() as client:
        response = await client.post(
            SETUP, json=_setup_body(), headers={**KEY, **_bearer(Role.ADVISOR)}
        )
    assert response.status_code == 404


async def test_the_number_change_route_exists_for_the_lead() -> None:
    async with _client() as client:
        response = await client.post(CHANGE, json=_change_body(), headers=_bearer(Role.LEAD))
    assert response.status_code == 400


async def test_an_advisor_is_not_found_for_a_number_change() -> None:
    async with _client() as client:
        response = await client.post(
            CHANGE, json=_change_body(), headers={**KEY, **_bearer(Role.ADVISOR)}
        )
    assert response.status_code == 404


async def test_set_up_without_an_idempotency_key_is_a_bad_request() -> None:
    async with _client() as client:
        response = await client.post(SETUP, json=_setup_body(), headers=_bearer(Role.LEAD))
    assert response.status_code == 400


async def test_a_number_change_without_an_idempotency_key_is_a_bad_request() -> None:
    async with _client() as client:
        response = await client.post(CHANGE, json=_change_body(), headers=_bearer(Role.LEAD))
    assert response.status_code == 400


async def test_push_is_refused_for_a_new_service_outside_the_pilot() -> None:
    async with _client() as client:
        response = await client.post(
            SETUP,
            json=_setup_body(channel={"valueCode": "push"}),
            headers={**KEY, **_bearer(Role.LEAD)},
        )
    assert response.status_code == 400
    assert "channel" in response.text


async def test_an_invalid_mobile_is_refused_with_the_example_and_without_the_input() -> None:
    async with _client() as client:
        response = await client.post(
            SETUP,
            json=_setup_body(mobile={"valueString": "07700 9001x9"}),
            headers={**KEY, **_bearer(Role.LEAD)},
        )
    assert response.status_code == 400
    assert REFUSAL in response.text
    assert "9001x9" not in response.text


async def test_an_invalid_mobile_on_a_number_change_is_refused_without_the_input() -> None:
    async with _client() as client:
        response = await client.post(
            CHANGE,
            json=_change_body(mobile="07700 9004x6"),
            headers={**KEY, **_bearer(Role.LEAD)},
        )
    assert response.status_code == 400
    assert "9004x6" not in response.text


async def test_an_unknown_duration_is_refused() -> None:
    async with _client() as client:
        response = await client.post(
            CHANGE,
            json=_change_body(duration="next-century"),
            headers={**KEY, **_bearer(Role.LEAD)},
        )
    assert response.status_code == 400


async def test_the_number_ending_is_the_last_four_digits_of_the_national_form() -> None:
    assert number_ending("07700 900456") == "0456"
    assert number_ending("+447700 900456") == "0456"
