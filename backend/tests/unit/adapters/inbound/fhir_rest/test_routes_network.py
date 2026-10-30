"""The network read routes (TEN-059, DEC-548, DEC-132 item 4).

GET /networks, /network/{id}/board, /directory, /criteria. Each call runs a real app in process
with fake use cases that record what they were asked. The rules: a token's `networks` claim only
routes (a network id outside it is the same 404 as a network that does not exist, with no use case
run), the registry is the authority (the use case's NotFound and NotAllowed are that same 404), a
role that does not see a network is that 404 too, nothing is cached by a shared cache, and no body
names a tenant or a grant. Sample identifiers only.
"""

import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from diucs.adapters.inbound.fhir_rest.routes_network import NetworkServices
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from diucs.adapters.inbound.fhir_rest.app import create_app
from diucs.adapters.inbound.fhir_rest.auth import BFF_SECRET_NAME
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.tokens import TEST_BFF_SECRET, issue_test_token
from diucs.application.actor import Actor
from diucs.application.ports.outbound.projection import ProjectionEndReason
from diucs.application.use_cases.network_board_projector import network_board_to_dict
from diucs.application.use_cases.query_network_board import NetworkBoardView
from diucs.application.use_cases.query_network_directory import (
    NetworkCriteriaEntry,
    NetworkCriteriaView,
    NetworkDirectoryEntry,
    NetworkDirectoryView,
)
from diucs.domain.codes import NeedCategory, Role, ServiceCategory, Status
from diucs.domain.errors import NotAllowed, NotFound
from diucs.domain.model.network import DirectorySource
from diucs.domain.rules.listing import ListingPresentation
from diucs.domain.rules.network_board import NetworkBoard, NetworkBoardEntry
from diucs.domain.rules.pressure import Pressure
from diucs.domain.rules.projection import LocationProjection
from tests.support.edge import EDGE_NOW, TENANT_A, EdgeContainer, active_tenants

pytestmark = pytest.mark.asyncio(loop_scope="session")

NET = "net-pilot"
AT = datetime(2026, 10, 23, 13, 0, tzinfo=UTC)
NOT_FOUND_BODY = None  # filled by the first test that reads it


def _board() -> NetworkBoardView:
    entry = NetworkBoardEntry(
        row_ref="lst-1",
        organisation_name="B Trust",
        service_name="UCR West",
        category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
        presentation=ListingPresentation.SHOWN,
        status=Status.LIMITED,
        unit_label="referrals",
        effective_available=2,
        over_by=None,
        used=8,
        established=10,
        reported_at=AT,
        stale_warning=False,
        was_due_at=None,
        source=DirectorySource.MANUAL,
    )
    return NetworkBoardView(
        NetworkBoard((entry,), Pressure.WATCH, False, EDGE_NOW),
        "Capacity board",
        "Urgent pathway",
        "Europe/London",
    )


def _directory(ended: bool = False) -> NetworkDirectoryView:
    entry = NetworkDirectoryEntry(
        row_ref="lst-1",
        organisation_name="B Trust",
        service_name="UCR West",
        category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
        active=True,
        source=DirectorySource.MANUAL,
        contact_label=None,
        contact_phone=None,
        location=LocationProjection("West site", "DT4", "Weymouth", 50.6, -2.45),
        opening_hours=(),
        presentation=ListingPresentation.SHOWN,
        ended_at=AT if ended else None,
        end_reason=ProjectionEndReason.LEFT if ended else None,
    )
    return NetworkDirectoryView((entry,), "Capacity board", "Urgent pathway", "Europe/London")


def _criteria() -> NetworkCriteriaView:
    entry = NetworkCriteriaEntry(
        row_ref="lst-1",
        organisation_name="B Trust",
        service_name="UCR West",
        version=3,
        age_min=18,
        age_max=None,
        districts=("DT1", "DT4"),
        accepts=(NeedCategory.FRAILTY,),
        excludes=(NeedCategory.IV_THERAPY,),
        review_by=date(2027, 4, 29),
        ended_at=None,
        end_reason=None,
    )
    return NetworkCriteriaView((entry,), "Capacity board", "Urgent pathway", "Europe/London")


class _Recorder:
    def __init__(self, result: Any) -> None:
        self.result = result
        self.calls: list[tuple[Any, ...]] = []
        self.error: Exception | None = None

    async def _answer(self, *call: Any) -> Any:
        self.calls.append(call)
        if self.error is not None:
            raise self.error
        return self.result


class _Projector(_Recorder):
    async def get_board(self, actor: Actor, network_id: str) -> NetworkBoardView:
        return await self._answer(actor.tenant_id, network_id)


class _Query(_Recorder):
    async def execute(self, actor: Actor, network_id: str, *, history: bool = False) -> Any:
        return await self._answer(actor.tenant_id, network_id, history)


class _Networks:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def networks_of(self, actor: Actor) -> list[Any]:
        self.calls.append(actor.tenant_id)
        return [_Context()]


class _Context:
    class network:
        id = NET
        name = "Pilot network"

    class settings:
        system_name = "Capacity board"
        pathway_name = "Urgent pathway"
        time_zone = "Europe/London"


def build() -> tuple[FastAPI, NetworkServices]:
    container = EdgeContainer(tenants=active_tenants(TENANT_A))
    app = create_app(container)  # type: ignore[arg-type]
    app.state.secrets = FixedSecretStore({BFF_SECRET_NAME: TEST_BFF_SECRET})
    services = NetworkServices(
        access=_Networks(),  # type: ignore[arg-type]
        projector=_Projector(_board()),  # type: ignore[arg-type]
        directory=_Query(_directory()),  # type: ignore[arg-type]
        criteria=_Query(_criteria()),  # type: ignore[arg-type]
    )
    app.state.network_services = services
    return app, services


def client_for(app: FastAPI) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    )


def bearer(
    networks: tuple[str, ...] = (NET,), role: Role = Role.ADVISOR, tenant: str = TENANT_A
) -> dict[str, str]:
    token = issue_test_token(role, [], "prac-1", tenant=tenant, networks=networks)
    return {"Authorization": f"Bearer {token}"}


def calls(services: NetworkServices) -> int:
    return sum(
        len(part.calls)  # type: ignore[attr-defined]
        for part in (services.projector, services.directory, services.criteria)
    )


# the board


async def test_a_member_reads_the_board_as_the_cached_encoding() -> None:
    app, services = build()
    async with client_for(app) as client:
        response = await client.get(f"/network/{NET}/board", headers=bearer())
    assert response.status_code == 200
    assert response.json() == json.loads(json.dumps(network_board_to_dict(_board())))
    assert response.headers["cache-control"] == "no-store"
    assert services.projector.calls == [(TENANT_A, NET)]  # type: ignore[attr-defined]


async def test_a_network_outside_the_claim_is_the_not_found_answer_and_runs_nothing() -> None:
    app, services = build()
    async with client_for(app) as client:
        response = await client.get("/network/net-other/board", headers=bearer())
    assert response.status_code == 404
    assert calls(services) == 0


async def test_a_token_with_no_networks_is_the_same_answer() -> None:
    app, services = build()
    async with client_for(app) as client:
        no_claim = await client.get(f"/network/{NET}/board", headers=bearer(networks=()))
    assert no_claim.status_code == 404 and calls(services) == 0


async def test_every_refusal_is_one_body() -> None:
    app, services = build()
    bodies = set()
    async with client_for(app) as client:
        bodies.add((await client.get("/network/net-other/board", headers=bearer())).text)
        bodies.add(
            (await client.get(f"/network/{NET}/board", headers=bearer(role=Role.REPORTER))).text
        )
        services.projector.error = NotFound("the network was not found")  # type: ignore[attr-defined]
        bodies.add((await client.get(f"/network/{NET}/board", headers=bearer())).text)
        services.projector.error = NotAllowed("this role cannot see a network")  # type: ignore[attr-defined]
        bodies.add((await client.get(f"/network/{NET}/board", headers=bearer())).text)
    assert len(bodies) == 1
    assert NET not in bodies.pop()


async def test_a_claim_is_not_enough_the_registrys_not_found_wins() -> None:
    app, services = build()
    services.projector.error = NotFound("the network was not found")  # type: ignore[attr-defined]
    async with client_for(app) as client:
        response = await client.get(f"/network/{NET}/board", headers=bearer())
    assert response.status_code == 404
    assert len(services.projector.calls) == 1  # type: ignore[attr-defined]


async def test_no_token_is_401() -> None:
    app, services = build()
    async with client_for(app) as client:
        response = await client.get(f"/network/{NET}/board")
    assert response.status_code == 401 and calls(services) == 0


@pytest.mark.parametrize(
    "network_id", ["tenant-a", "NET-PILOT", "net-", "net-a%20b", "net-" + "x" * 80]
)
async def test_a_path_that_is_not_a_network_id_runs_nothing(network_id: str) -> None:
    app, services = build()
    async with client_for(app) as client:
        response = await client.get(
            f"/network/{network_id}/board",
            headers=bearer(
                networks=(network_id,)
                if network_id.startswith("net-") and len(network_id) < 30
                else ()
            ),
        )
    assert response.status_code in (400, 404, 422)
    assert calls(services) == 0


async def test_a_body_or_a_query_cannot_name_another_network_or_tenant() -> None:
    app, services = build()
    async with client_for(app) as client:
        response = await client.get(
            f"/network/{NET}/board?network=net-other&tenant=tenant-z",
            headers={**bearer(), "X-Tenant": "tenant-z"},
        )
    assert response.status_code == 200
    assert services.projector.calls == [(TENANT_A, NET)]  # type: ignore[attr-defined]


# the directory and criteria


async def test_the_directory_is_read_live_by_default_and_as_history_on_request() -> None:
    app, services = build()
    async with client_for(app) as client:
        live = await client.get(f"/network/{NET}/directory", headers=bearer())
        history = await client.get(f"/network/{NET}/directory?history=true", headers=bearer())
    assert services.directory.calls == [(TENANT_A, NET, False), (TENANT_A, NET, True)]  # type: ignore[attr-defined]
    [entry] = live.json()["entries"]
    assert entry["organisation_name"] == "B Trust" and entry["ended_at"] is None
    assert entry["location"] == {
        "location_name": "West site",
        "postal_district": "DT4",
        "city": "Weymouth",
        "latitude": 50.6,
        "longitude": -2.45,
    }
    assert live.json()["time_zone"] == "Europe/London"
    assert history.status_code == 200


async def test_a_directory_history_entry_carries_the_date_and_the_reason() -> None:
    app, services = build()
    services.directory.result = _directory(ended=True)  # type: ignore[attr-defined]
    async with client_for(app) as client:
        response = await client.get(f"/network/{NET}/directory?history=true", headers=bearer())
    [entry] = response.json()["entries"]
    assert entry["ended_at"] == "2026-10-23T13:00:00+00:00" and entry["end_reason"] == "left"


async def test_the_criteria_are_returned_with_plain_codes() -> None:
    app, _ = build()
    async with client_for(app) as client:
        response = await client.get(f"/network/{NET}/criteria", headers=bearer())
    [entry] = response.json()["entries"]
    assert entry["version"] == 3 and entry["review_by"] == "2027-04-29"
    assert entry["districts"] == ["DT1", "DT4"]
    assert entry["accepts"] == [NeedCategory.FRAILTY.value]
    assert entry["excludes"] == [NeedCategory.IV_THERAPY.value]


@pytest.mark.parametrize("suffix", ["directory", "criteria"])
async def test_the_directory_and_criteria_give_the_same_refusals(suffix: str) -> None:
    app, services = build()
    async with client_for(app) as client:
        outside = await client.get(f"/network/net-other/{suffix}", headers=bearer())
        wrong_role = await client.get(f"/network/{NET}/{suffix}", headers=bearer(role=Role.WALL))
    assert outside.status_code == wrong_role.status_code == 404
    assert outside.text == wrong_role.text and calls(services) == 0


async def test_a_bad_history_flag_runs_nothing() -> None:
    app, services = build()
    async with client_for(app) as client:
        response = await client.get(f"/network/{NET}/directory?history=maybe", headers=bearer())
    assert response.status_code in (400, 422) and calls(services) == 0


# the list of networks


async def test_the_list_of_networks_is_the_registrys_not_the_claims() -> None:
    app, services = build()
    async with client_for(app) as client:
        response = await client.get("/networks", headers=bearer(networks=()))
    assert response.status_code == 200
    assert response.json() == {
        "networks": [
            {
                "id": NET,
                "name": "Pilot network",
                "system_name": "Capacity board",
                "pathway_name": "Urgent pathway",
                "time_zone": "Europe/London",
            }
        ]
    }
    assert services.access.calls == [TENANT_A]  # type: ignore[attr-defined]


async def test_a_role_that_never_sees_a_network_gets_the_not_found_answer_for_the_list() -> None:
    app, services = build()
    async with client_for(app) as client:
        response = await client.get("/networks", headers=bearer(role=Role.REPORTER))
    assert response.status_code == 404 and services.access.calls == []  # type: ignore[attr-defined]


async def test_an_app_with_no_network_services_fails_closed() -> None:
    app, _ = build()
    del app.state.network_services
    async with client_for(app) as client:
        response = await client.get(f"/network/{NET}/board", headers=bearer())
    assert response.status_code == 500


async def test_the_stream_route_gives_the_same_refusals_as_the_other_network_routes() -> None:
    app, services = build()
    async with client_for(app) as client:
        outside = await client.get("/network/net-other/events", headers=bearer())
        wrong_role = await client.get(f"/network/{NET}/events", headers=bearer(role=Role.REPORTER))
        anonymous = await client.get(f"/network/{NET}/events")
    assert (outside.status_code, wrong_role.status_code, anonymous.status_code) == (404, 404, 401)
    assert outside.text == wrong_role.text and calls(services) == 0
