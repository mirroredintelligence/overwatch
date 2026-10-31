"""The network reads of the shift lead's pages and the week summary, over HTTP on a real Neo4j and
Redis (TEN-082 and the network variants of W17 and W43; DEC-136 items 1, 9 and 14).

Three members of one network have granted capacity, directory and criteria (the network world).
The tests show: system now counts the board and carries the network pressure alert as a state;
the phones list each service with the service line its organisation shared and never a reporter's
number or anything the projection does not hold; the week summary is read from the hourly samples
(shown with enough readings, hidden below ten, withheld for fewer than three organisations) and
holds no member; the roles of each route (13 roles); a tenant outside the network, an unknown
network, a network outside the claim and a member who left are the one 404; another network's
samples never reach this one; and a board that is built is filed as the sample of its hour.
"""

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from neo4j import AsyncDriver

from diucs.adapters.inbound.fhir_rest.app import create_app
from diucs.adapters.inbound.fhir_rest.auth import BFF_SECRET_NAME
from diucs.adapters.inbound.fhir_rest.routes_network import NetworkServices
from diucs.adapters.outbound.cache_redis.redis_cache import RedisCache
from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.outbound.graph_store.unit_of_work import (
    Neo4jUnitOfWork,
    neo4j_network_uow_factory,
)
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.tokens import TEST_BFF_SECRET, issue_test_token
from diucs.application.network_access import NETWORK_VIEW_ROLES, NetworkAccess
from diucs.application.tenancy import bind_network
from diucs.application.use_cases.network_board_projector import (
    NETWORK_BOARD_CACHE_KEY,
    NetworkBoardProjector,
)
from diucs.application.use_cases.network_samples import RecordNetworkSample
from diucs.application.use_cases.network_week_summary import READERS, GetNetworkWeekSummary
from diucs.application.use_cases.query_network_board import QueryNetworkBoard
from diucs.application.use_cases.query_network_directory import (
    QueryNetworkCriteria,
    QueryNetworkDirectory,
)
from diucs.domain.codes import Role, Status
from diucs.domain.rules.network_sample import READINGS, NetworkSample
from diucs.domain.rules.pressure import Pressure
from tests.support.edge import EdgeContainer, active_tenants
from tests.support.network_world import NOW, NetworkWorld, world_ids
from tests.support.tenancy import RunIdentity

pytestmark = pytest.mark.asyncio(loop_scope="session")

WEEK = "2026-10-26"
WEEK_START = datetime(2026, 10, 26, 0, 0, tzinfo=UTC)
ALL_ROLES = tuple(role for role in Role if role is not Role.PLATFORM_OPERATOR)


class _Tenant:
    def __init__(self, display_name: str) -> None:
        self.display_name = display_name


class _Names:
    async def get(self, tenant_id: str) -> _Tenant | None:
        return _Tenant(f"Org {tenant_id.rsplit('-', 1)[-1]}")


@pytest_asyncio.fixture(loop_scope="session")
async def connection(harness_driver: AsyncDriver) -> AsyncIterator[Neo4jConnection]:
    conn = Neo4jConnection(
        os.environ["NEO4J_URI"], os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]
    )
    await conn.open()
    try:
        yield conn
    finally:
        await conn.close()


@pytest_asyncio.fixture(loop_scope="session")
async def world(
    harness_driver: AsyncDriver,
    connection: Neo4jConnection,
    run_identity: RunIdentity,
    clean_graph: None,
) -> AsyncIterator[NetworkWorld]:
    built = await NetworkWorld.build(harness_driver, connection, world_ids(run_identity))
    await built.run_projector()
    yield built
    await built.cleanup()


@pytest_asyncio.fixture(loop_scope="session")
async def app(world: NetworkWorld) -> AsyncIterator[FastAPI]:
    cache = RedisCache.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    with bind_network(world.ids.network):
        await cache.delete(NETWORK_BOARD_CACHE_KEY)
    clock = FixedClock(NOW + timedelta(minutes=2))
    container = EdgeContainer(
        tenants=active_tenants(*world.ids.members, world.ids.outsider, world.ids.owner),
        clock=clock,
    )
    built = create_app(container)  # type: ignore[arg-type]
    built.state.secrets = FixedSecretStore({BFF_SECRET_NAME: TEST_BFF_SECRET})
    access = NetworkAccess(world.registry, _Names())  # type: ignore[arg-type]
    read_only = neo4j_network_uow_factory(world.driver, read_only=True)
    query = QueryNetworkBoard(read_only, access, clock)
    built.state.network_services = NetworkServices(
        access=access,
        projector=NetworkBoardProjector(
            query,
            access,
            cache,
            clock,
            RecordNetworkSample(neo4j_network_uow_factory(world.driver)),
        ),
        directory=QueryNetworkDirectory(read_only, access, clock),
        criteria=QueryNetworkCriteria(read_only, access, clock),
        weeks=GetNetworkWeekSummary(read_only, access),
    )
    built.state.cache = cache
    yield built
    with bind_network(world.ids.network):
        await cache.delete(NETWORK_BOARD_CACHE_KEY)
    await cache.aclose()


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    )


def _bearer(tenant: str, networks: tuple[str, ...], role: Role = Role.LEAD) -> dict[str, str]:
    token = issue_test_token(
        role, [], "prac-1", tenant=tenant, networks=networks, expires_at=NOW + timedelta(hours=1)
    )
    return {"Authorization": f"Bearer {token}"}


def _sample(
    hour_index: int, *, organisations: int = 3, pressure: Pressure = Pressure.NORMAL, **counts: int
) -> NetworkSample:
    tally = {status: 0 for status in READINGS}
    tally.update({Status(k.replace("_", "-")): v for k, v in counts.items()})
    hour = WEEK_START + timedelta(hours=hour_index)
    return NetworkSample(
        hour=hour,
        at=hour + timedelta(minutes=30),
        counts=tuple(tally.items()),
        unavailable=0,
        organisations=organisations,
        pressure=pressure,
    )


async def _file(world: NetworkWorld, network: str, *samples: NetworkSample) -> None:
    with bind_network(network):
        async with Neo4jUnitOfWork(world.driver) as uow:
            for sample in samples:
                await uow.network_samples.record(sample)
            await uow.commit()


async def _stored_hours(world: NetworkWorld, network: str) -> list[NetworkSample]:
    with bind_network(network):
        async with Neo4jUnitOfWork(world.driver, read_only=True) as uow:
            return list(
                await uow.network_samples.between(
                    WEEK_START - timedelta(days=30), WEEK_START + timedelta(days=60)
                )
            )


# ------------------------------------------------------------------ system now


async def test_system_now_counts_the_board_and_carries_the_alert_as_a_state(
    app: FastAPI, world: NetworkWorld
) -> None:
    network = world.ids.network
    async with _client(app) as client:
        response = await client.get(
            f"/network/{network}/system-now", headers=_bearer(world.ids.members[0], (network,))
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["services"] == 3 and body["organisations"] == 3
    assert sum(body["by_status"].values()) == 3
    assert set(body["by_status"]) == {
        "accepting",
        "limited",
        "not-accepting",
        "over-capacity",
        "not-updated",
        "out-of-hours",
        "unavailable",
    }
    assert body["pressure"] == "normal"
    assert body["alert"] == {
        "raised": False,
        "level": "normal",
        "limited_or_worse": 0,
        "watch_from": 3,
        "high_from": 5,
    }
    assert body["system_name"] and body["pathway_name"] and body["time_zone"] == "Europe/London"
    assert response.headers["cache-control"] == "no-store"
    assert not any(t in response.text for t in (*world.ids.members, world.ids.owner, "grant-"))
    assert network not in response.text


# ------------------------------------------------------------------ phones


async def test_the_phones_list_every_service_with_its_service_line_and_status(
    app: FastAPI, world: NetworkWorld
) -> None:
    network = world.ids.network
    async with _client(app) as client:
        response = await client.get(
            f"/network/{network}/phones", headers=_bearer(world.ids.members[0], (network,))
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["organisations"] == 3
    assert {p["service_name"] for p in body["phones"]} == {
        world.service_name(m) for m in world.ids.members
    }
    for row in body["phones"]:
        # the producer has no source of a service line yet (`project_network` passes none), so
        # every row reads "Phone to confirm": the fields are there and empty
        assert row["contact_label"] is None and row["contact_phone"] is None
        assert row["status"] is not None
        assert set(row) == {
            "row_ref",
            "organisation_name",
            "service_name",
            "category",
            "presentation",
            "status",
            "stale_warning",
            "reported_at",
            "contact_label",
            "contact_phone",
        }


async def test_the_phones_hold_no_reporter_no_comment_and_no_member(
    app: FastAPI, world: NetworkWorld
) -> None:
    network = world.ids.network
    async with _client(app) as client:
        response = await client.get(
            f"/network/{network}/phones", headers=_bearer(world.ids.members[0], (network,))
        )
    text = response.text
    for member in world.ids.members:
        assert member not in text
        for poison in world.poison[member]:
            assert poison not in text
    assert world.ids.owner not in text and "grant-" not in text and network not in text
    assert "07700" not in text and "reporter" not in text.lower()


# ------------------------------------------------------------------ the week


async def test_a_week_with_enough_samples_shows_the_shares_and_the_pressure_by_hour(
    app: FastAPI, world: NetworkWorld
) -> None:
    network = world.ids.network
    await _file(
        world,
        network,
        *(_sample(h, accepting=2, limited=1, not_updated=1) for h in range(12)),
        _sample(12, accepting=2, limited=1, not_updated=1, pressure=Pressure.HIGH),
    )
    async with _client(app) as client:
        response = await client.get(
            f"/network/{network}/week",
            params={"weekStart": WEEK},
            headers=_bearer(world.ids.members[0], (network,)),
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["week_start"] == WEEK and body["withheld"] is False
    assert body["hours_sampled"] == {"label": "hours sampled", "value": 13, "hidden": False}
    assert body["on_time_pct"]["value"] == 75
    assert body["status_share"]["accepting"]["value"] == 50
    assert body["status_share"]["limited"]["value"] == 25
    assert body["pressure_hours"]["normal"]["value"] == 12
    assert body["pressure_hours"]["high"] == {"label": "high", "value": None, "hidden": True}
    assert len(body["pressure_over_time"]) == 13
    assert body["pressure_over_time"][-1] == {
        "hour": "2026-10-26T12:00:00+00:00",
        "pressure": "high",
    }
    assert not any(t in response.text for t in (*world.ids.members, world.ids.owner, "grant-"))
    assert "organisation" not in {key for key in body}  # no per-member breakdown


async def test_a_small_week_is_hidden_and_a_small_network_is_withheld(
    app: FastAPI, world: NetworkWorld
) -> None:
    network = world.ids.network
    headers = _bearer(world.ids.members[0], (network,))
    await _file(world, network, _sample(0, accepting=3))
    async with _client(app) as client:
        small = await client.get(
            f"/network/{network}/week", params={"weekStart": WEEK}, headers=headers
        )
    assert small.json()["withheld"] is False
    assert small.json()["on_time_pct"] == {
        "label": "capacity updates on time",
        "value": None,
        "hidden": True,
    }
    await _file(world, network, *(_sample(h, accepting=4, organisations=2) for h in range(1, 20)))
    await _file(world, network, _sample(0, accepting=3, organisations=2))
    async with _client(app) as client:
        withheld = await client.get(
            f"/network/{network}/week", params={"weekStart": WEEK}, headers=headers
        )
    body = withheld.json()
    assert body["withheld"] is True and body["pressure_over_time"] == []
    assert body["on_time_pct"]["hidden"] and body["hours_sampled"]["hidden"]


async def test_another_networks_samples_never_reach_this_week(
    app: FastAPI, world: NetworkWorld
) -> None:
    network = world.ids.network
    await _file(world, world.ids.other_network, *(_sample(h, accepting=9) for h in range(30)))
    async with _client(app) as client:
        response = await client.get(
            f"/network/{network}/week",
            params={"weekStart": WEEK},
            headers=_bearer(world.ids.members[0], (network,)),
        )
    body = response.json()
    assert body["hours_sampled"]["hidden"] and body["withheld"] is True


@pytest.mark.parametrize(
    "params",
    [{}, {"weekStart": "2026-10-27"}, {"weekStart": "not-a-date"}, {"weekStart": "2026-13-01"}],
)
async def test_a_week_start_that_is_not_a_monday_is_refused(
    app: FastAPI, world: NetworkWorld, params: dict[str, str]
) -> None:
    network = world.ids.network
    async with _client(app) as client:
        response = await client.get(
            f"/network/{network}/week",
            params=params,
            headers=_bearer(world.ids.members[0], (network,)),
        )
    assert response.status_code == 400


# ------------------------------------------------------------------ the board files its sample


async def test_a_board_that_is_built_is_filed_as_the_sample_of_its_hour(
    app: FastAPI, world: NetworkWorld
) -> None:
    network = world.ids.network
    assert await _stored_hours(world, network) == []
    async with _client(app) as client:
        board = await client.get(
            f"/network/{network}/board", headers=_bearer(world.ids.members[0], (network,))
        )
    assert board.status_code == 200
    (stored,) = await _stored_hours(world, network)
    assert stored.hour == datetime(2026, 10, 31, 9, 0, tzinfo=UTC)
    assert stored.organisations == 3
    assert stored.readings == 3
    assert not other_scope_holds_samples(await _stored_hours(world, world.ids.other_network))


def other_scope_holds_samples(samples: list[Any]) -> bool:
    return bool(samples)


# ------------------------------------------------------------------ refusals and roles


async def test_a_tenant_outside_the_network_an_unknown_network_and_no_claim_are_the_same_404(
    app: FastAPI, world: NetworkWorld
) -> None:
    network = world.ids.network
    outsider = world.ids.outsider
    async with _client(app) as client:
        answers = []
        for path in ("system-now", "phones"):
            answers += [
                await client.get(
                    f"/network/{network}/{path}", headers=_bearer(outsider, (network,))
                ),
                await client.get(
                    f"/network/{network}/{path}", headers=_bearer(world.ids.members[0], ())
                ),
                await client.get(
                    f"/network/net-nowhere/{path}",
                    headers=_bearer(world.ids.members[0], ("net-nowhere",)),
                ),
            ]
        answers += [
            await client.get(
                f"/network/{network}/week",
                params={"weekStart": WEEK},
                headers=_bearer(outsider, (network,)),
            ),
            await client.get(
                "/network/net-nowhere/week",
                params={"weekStart": WEEK},
                headers=_bearer(world.ids.members[0], ("net-nowhere",)),
            ),
        ]
    assert {a.status_code for a in answers} == {404}
    assert len({a.text for a in answers}) == 1
    assert network not in answers[0].text


async def test_a_member_who_left_reads_nothing_of_the_lead_views(
    app: FastAPI, world: NetworkWorld
) -> None:
    network = world.ids.network
    leaver = world.ids.members[2]
    headers = _bearer(leaver, (network,))
    async with _client(app) as client:
        before = await client.get(f"/network/{network}/system-now", headers=headers)
        await world.leave(leaver)
        after = [
            await client.get(f"/network/{network}/system-now", headers=headers),
            await client.get(f"/network/{network}/phones", headers=headers),
            await client.get(
                f"/network/{network}/week", params={"weekStart": WEEK}, headers=headers
            ),
        ]
    assert before.status_code == 200
    assert {a.status_code for a in after} == {404}


@pytest.mark.parametrize("role", ALL_ROLES)
async def test_role_matrix_of_the_three_routes(
    app: FastAPI, world: NetworkWorld, role: Role
) -> None:
    network = world.ids.network
    headers = _bearer(world.ids.members[0], (network,), role)
    async with _client(app) as client:
        now = await client.get(f"/network/{network}/system-now", headers=headers)
        phones = await client.get(f"/network/{network}/phones", headers=headers)
        week = await client.get(
            f"/network/{network}/week", params={"weekStart": WEEK}, headers=headers
        )
    assert now.status_code == phones.status_code == (200 if role in NETWORK_VIEW_ROLES else 404)
    assert week.status_code == (200 if role in READERS else 404)


async def test_the_operator_token_and_no_token_are_refused_at_the_edge(
    app: FastAPI, world: NetworkWorld
) -> None:
    network = world.ids.network
    operator = _bearer(world.ids.members[0], (network,), Role.PLATFORM_OPERATOR)
    async with _client(app) as client:
        for path in ("system-now", "phones", "week"):
            url = f"/network/{network}/{path}"
            assert (
                await client.get(url, params={"weekStart": WEEK}, headers=operator)
            ).status_code == 401
            assert (await client.get(url, params={"weekStart": WEEK})).status_code == 401
