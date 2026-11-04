"""The advisor's postcode lookup (DEC-1340): GET /clinical/postcodes/locate answers from the
geocoder for the postcode typed, and says so when it cannot answer. No Neo4j, no network."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from overwatch.adapters.inbound.fhir_rest.app import create_app
from overwatch.adapters.inbound.fhir_rest.auth import BFF_SECRET_NAME
from overwatch.adapters.testing.fixed_clock import FixedClock
from overwatch.adapters.testing.fixed_geo import FixedGeocoder
from overwatch.adapters.testing.fixed_ids import SequentialIds
from overwatch.adapters.testing.fixed_secrets import FixedSecretStore
from overwatch.adapters.testing.tokens import (
    TEST_BFF_SECRET,
    default_token_tenant,
    issue_test_token,
)
from overwatch.application.ports.outbound.geo import AddressCandidate, LatLon
from overwatch.application.ports.outbound.lookups import TransientLookupError
from overwatch.domain.codes import Role
from tests.support.edge import active_tenants

NOW = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)
LOCATE = "/clinical/postcodes/locate"
ADVISOR = {"Authorization": f"Bearer {issue_test_token(Role.CLINICAL, [], 'advisor-1')}"}
DT4_4GB = AddressCandidate(
    uprn="100000000001",
    line="1 Sample Road",
    town="Dorchester",
    postcode="DT4 4GB",
    position=LatLon(50.609209, -2.456099),
)


@dataclass(frozen=True)
class _RouteContainer:
    clock: FixedClock
    ids: SequentialIds
    uow_factory: Any
    secrets: FixedSecretStore
    tenants: Any
    geocoder: Any


@asynccontextmanager
async def _client(geocoder: Any) -> AsyncIterator[AsyncClient]:
    container = _RouteContainer(
        clock=FixedClock(NOW),
        ids=SequentialIds(),
        uow_factory=None,
        secrets=FixedSecretStore({BFF_SECRET_NAME: TEST_BFF_SECRET}),
        tenants=active_tenants(default_token_tenant()),
        geocoder=geocoder,
    )
    app: FastAPI = create_app(container)  # type: ignore[arg-type]
    app.state.secrets = FixedSecretStore({BFF_SECRET_NAME: TEST_BFF_SECRET})
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        yield client


class _Down:
    async def find_addresses(self, postcode: str) -> list[AddressCandidate]:
        raise TransientLookupError


async def test_a_postcode_that_is_found_gives_its_position() -> None:
    async with _client(FixedGeocoder({"DT4 4GB": [DT4_4GB]})) as http:
        response = await http.get(f"{LOCATE}?postcode=dt44gb", headers=ADVISOR)

    assert response.status_code == 200, response.text
    assert response.json() == {"status": "found", "lat": 50.609209, "lon": -2.456099}


async def test_a_postcode_that_is_not_found_says_so() -> None:
    async with _client(FixedGeocoder({})) as http:
        response = await http.get(f"{LOCATE}?postcode=DT4%208XX", headers=ADVISOR)

    assert response.json() == {"status": "not-found"}


async def test_a_lookup_that_cannot_answer_says_unavailable_and_does_not_fail_the_form() -> None:
    async with _client(_Down()) as http:
        response = await http.get(f"{LOCATE}?postcode=DT4%204GB", headers=ADVISOR)

    assert response.status_code == 200
    assert response.json() == {"status": "unavailable"}


async def test_text_that_is_not_a_full_postcode_is_refused_and_not_echoed() -> None:
    async with _client(FixedGeocoder({})) as http:
        response = await http.get(f"{LOCATE}?postcode=hello-there", headers=ADVISOR)

    assert response.status_code == 400
    assert "hello-there" not in response.text
