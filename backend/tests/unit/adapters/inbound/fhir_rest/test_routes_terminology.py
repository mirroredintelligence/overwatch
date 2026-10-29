"""The Pathways Dx lookup route (R16), in-process and with no Neo4j.

The route reads only the caller's role, the request and the terminology port. So the app here is
built on a container of fixed parts: a fixed clock, sequential ids, a unit-of-work factory that
must never be called, and FixedTerminology holding fake Dx codes. The Neo4j-backed route tests
(api_client) run with the verification stage. Sample values only: these are not NHS Pathways codes.
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
from diucs.adapters.testing.fixed_terminology import FixedTerminology
from diucs.adapters.testing.tokens import TEST_BFF_SECRET, issue_test_token
from diucs.domain.codes import Role

pytestmark = pytest.mark.asyncio(loop_scope="session")

ROUTE = "/terminology/pathways-dx"
NOW = datetime(2026, 10, 23, 13, 12, tzinfo=UTC)
ENTRIES = [(f"DxSAMPLE{n:02d}", f"Sample disposition {n} (not a real code)") for n in range(1, 11)]
TOO_SHORT = "Type at least 2 characters"


def _as_json(entries: list[tuple[str, str]]) -> list[dict[str, str]]:
    return [{"code": code, "display": display} for code, display in entries]


@dataclass(frozen=True)
class _RouteContainer:
    clock: FixedClock
    ids: SequentialIds
    uow_factory: Any
    terminology: FixedTerminology


def _no_unit_of_work() -> Any:
    raise AssertionError("the Dx lookup opens no unit of work")


@asynccontextmanager
async def _client(entries: list[tuple[str, str]]) -> AsyncIterator[AsyncClient]:
    container = _RouteContainer(
        clock=FixedClock(NOW),
        ids=SequentialIds(),
        uow_factory=_no_unit_of_work,
        terminology=FixedTerminology({}, {}, pathways_dx=entries),
    )
    app: FastAPI = create_app(container)
    app.state.secrets = FixedSecretStore({BFF_SECRET_NAME: TEST_BFF_SECRET})
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        yield client


def _bearer(role: Role) -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_test_token(role, [], 'prac-1')}"}


async def test_an_advisor_gets_every_match_as_a_code_and_a_display() -> None:
    async with _client(ENTRIES) as client:
        response = await client.get(ROUTE, params={"q": "sa"}, headers=_bearer(Role.ADVISOR))

    assert response.status_code == 200
    assert response.json() == _as_json(ENTRIES)


async def test_each_result_carries_only_a_code_and_a_display() -> None:
    async with _client(ENTRIES) as client:
        response = await client.get(ROUTE, params={"q": "sa"}, headers=_bearer(Role.ADVISOR))

    items = response.json()
    assert items, "the check must see at least one result, or it passes on an empty list"
    assert all(set(item) == {"code", "display"} for item in items)


async def test_a_clinician_may_search_too() -> None:
    async with _client(ENTRIES) as client:
        response = await client.get(ROUTE, params={"q": "sa"}, headers=_bearer(Role.CLINICAL))

    assert response.status_code == 200


@pytest.mark.parametrize("text", ["s", " s "])
async def test_a_search_under_two_characters_is_refused_with_400(text: str) -> None:
    async with _client(ENTRIES) as client:
        response = await client.get(ROUTE, params={"q": text}, headers=_bearer(Role.ADVISOR))

    assert response.status_code == 400
    issue = response.json()["issue"][0]
    assert issue["code"] == "invalid"
    assert issue["diagnostics"] == TOO_SHORT


async def test_a_missing_search_text_is_refused_with_400() -> None:
    async with _client(ENTRIES) as client:
        response = await client.get(ROUTE, headers=_bearer(Role.ADVISOR))

    assert response.status_code == 400


async def test_at_most_twenty_matches_are_returned_in_code_order() -> None:
    many = [(f"DxT{n:02d}", f"Test disposition {n}") for n in range(25)]
    async with _client(many) as client:
        response = await client.get(ROUTE, params={"q": "test"}, headers=_bearer(Role.ADVISOR))

    assert response.status_code == 200
    assert response.json() == _as_json(many[:20])


@pytest.mark.parametrize(
    "role", [role for role in Role if role not in (Role.ADVISOR, Role.CLINICAL)]
)
async def test_a_role_other_than_advisor_or_clinical_gets_a_not_found(role: Role) -> None:
    async with _client(ENTRIES) as client:
        response = await client.get(ROUTE, params={"q": "sa"}, headers=_bearer(role))

    assert response.status_code == 404
    assert response.json()["issue"][0]["code"] == "not-found"


async def test_a_reporter_with_too_short_text_still_gets_a_not_found() -> None:
    async with _client(ENTRIES) as client:
        response = await client.get(ROUTE, params={"q": "s"}, headers=_bearer(Role.REPORTER))

    assert response.status_code == 404


async def test_no_token_is_refused_with_401() -> None:
    async with _client(ENTRIES) as client:
        response = await client.get(ROUTE, params={"q": "sa"})

    assert response.status_code == 401
