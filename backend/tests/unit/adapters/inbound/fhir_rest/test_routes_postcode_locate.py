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


async def test_advisor_v2_may_look_a_postcode_up_but_the_analytics_user_may_not() -> None:
    v2 = {"Authorization": f"Bearer {issue_test_token(Role.ADVISOR_V2, [], 'advisor-v2-1')}"}
    analytics = {
        "Authorization": f"Bearer {issue_test_token(Role.ANALYTICS_USER, [], 'analyst-1')}"
    }
    async with _client(FixedGeocoder({"DT4 4GB": [DT4_4GB]})) as http:
        found = await http.get(f"{LOCATE}?postcode=dt44gb", headers=v2)
        suggested = await http.get("/clinical/postcodes?prefix=DT4", headers=v2)
        refused_locate = await http.get(f"{LOCATE}?postcode=dt44gb", headers=analytics)
        refused_suggest = await http.get("/clinical/postcodes?prefix=DT4", headers=analytics)

    assert found.status_code == 200 and found.json()["status"] == "found"
    assert suggested.status_code in (200, 500)  # the test container holds no postcode file
    assert refused_locate.status_code in (403, 404)
    assert refused_suggest.status_code in (403, 404)
