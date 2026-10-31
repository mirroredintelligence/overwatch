"""The network options of a case over HTTP on a real Neo4j (WB11, TEN-051, TEN-053, DEC-136 item
1).

Three members of one network have granted capacity, directory and criteria and had a service
admitted; the projector has run for all three. The advisor of the first member has a case in
their own tenant. `GET /network/{id}/options?case=` gives that advisor the services of the OTHER
members that meet the case's criteria, read only: with the status at the read, the figure's age,
the travel time and the service line. The tests show the three scopes keep apart (the case is
read in the advisor's tenant, the rows in the network, and nothing of the case reaches the
network or another member), the role matrix (only the roles that work a case), the one 404 of a
non-member, and the audit of what was shown.
"""

import os
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from neo4j import AsyncDriver

from diucs.adapters.inbound.fhir_rest.app import create_app
from diucs.adapters.inbound.fhir_rest.auth import BFF_SECRET_NAME
from diucs.adapters.inbound.fhir_rest.routes_network import NetworkServices
from diucs.adapters.outbound.audit_neo4j.audit_log import ensure_audit_head
from diucs.adapters.outbound.cache_redis.redis_cache import RedisCache
from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.outbound.graph_store.unit_of_work import (
    neo4j_network_uow_factory,
    neo4j_uow_factory,
)
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_geo import FixedPostcodeLocator, FixedTravelTime
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.tokens import TEST_BFF_SECRET, issue_test_token
from diucs.application.network_access import NetworkAccess
from diucs.application.ports.outbound.geo import LatLon, TravelRange
from diucs.application.projection import to_body
from diucs.application.tenancy import bind_network, bind_tenant
from diucs.application.use_cases.filter_network_options import FilterNetworkOptions
from diucs.application.use_cases.network_board_projector import (
    NETWORK_BOARD_CACHE_KEY,
    NetworkBoardProjector,
)
from diucs.application.use_cases.query_network_board import QueryNetworkBoard
from diucs.application.use_cases.query_network_directory import (
    QueryNetworkCriteria,
    QueryNetworkDirectory,
)
from diucs.domain.codes import AgeBand, NeedCategory, Role
from diucs.domain.events import ProjectionRequested
from diucs.domain.model.network import GrantScope
from diucs.domain.rules.projection import PROJECTION_ALLOWLIST_VERSION
from tests.support.booking_rig import open_case
from tests.support.edge import EdgeContainer, active_tenants
from tests.support.network_world import NetworkWorld, world_ids
from tests.support.projection_samples import (
    NOW as READ_AT,
)
from tests.support.projection_samples import (
    SERVICE_ID,
    sample_profile,
    sample_service_projection,
)
from tests.support.tenancy import RunIdentity

pytestmark = pytest.mark.asyncio(loop_scope="session")

ALL_ROLES = tuple(role for role in Role if role is not Role.PLATFORM_OPERATOR)
CASE_ROLES = (Role.ADVISOR, Role.CLINICAL)
CASE_ID = "case-net-1"
PATIENT_DISTRICT_CENTRE = LatLon(52.0, -1.4)


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
    # The advisor's own tenant keeps its own audit chain and the case: the three scopes are apart.
    for member in built.ids.members:
        with bind_tenant(member):
            await ensure_audit_head(harness_driver)
    yield built
    await built.cleanup()


async def _seed_case(
    world: NetworkWorld, tenant: str, case_id: str = CASE_ID, **changes: Any
) -> None:
    # Each case has its own reference: a tenant keeps one case to a reference.
    changes.setdefault("reference", str(1_000 + sum(case_id.encode()) % 8_000))
    with bind_tenant(tenant):
        async with neo4j_uow_factory(world.driver)() as uow:
            await uow.cases.add(open_case(case_id, **changes))
            await uow.commit()


@pytest_asyncio.fixture(loop_scope="session")
async def app(world: NetworkWorld) -> AsyncIterator[FastAPI]:
    cache = RedisCache.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    with bind_network(world.ids.network):
        await cache.delete(NETWORK_BOARD_CACHE_KEY)
    # Half an hour after the members' reports, so their figures are current: the status is worked
    # out at the time of the read, and a report two days old reads Not updated.
    clock = FixedClock(READ_AT)
    container = EdgeContainer(
        tenants=active_tenants(*world.ids.members, world.ids.outsider), clock=clock
    )
    built = create_app(container)  # type: ignore[arg-type]
    built.state.secrets = FixedSecretStore({BFF_SECRET_NAME: TEST_BFF_SECRET})
    access = NetworkAccess(world.registry, _Names())  # type: ignore[arg-type]
    factory = neo4j_network_uow_factory(world.driver, read_only=True)
    projector = NetworkBoardProjector(
        QueryNetworkBoard(factory, access, clock), access, cache, clock
    )
    directory = QueryNetworkDirectory(factory, access, clock)
    criteria = QueryNetworkCriteria(factory, access, clock)
    built.state.network_services = NetworkServices(
        access=access,
        projector=projector,
        directory=directory,
        criteria=criteria,
        options=FilterNetworkOptions(
            neo4j_uow_factory(world.driver),
            clock,
            access,
            projector,
            directory,
            criteria,
            FixedPostcodeLocator({}, {"DT4": PATIENT_DISTRICT_CENTRE}),
            FixedTravelTime(TravelRange(low_minutes=12, high_minutes=24, source="test fixed")),
        ),
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


def _bearer(tenant: str, networks: tuple[str, ...], role: Role = Role.ADVISOR) -> dict[str, str]:
    token = issue_test_token(
        role,
        [],
        "prac-1",
        tenant=tenant,
        networks=networks,
        expires_at=READ_AT + timedelta(hours=1),
    )
    return {"Authorization": f"Bearer {token}"}


def _url(world: NetworkWorld, case: str = CASE_ID) -> str:
    return f"/network/{world.ids.network}/options?case={case}"


async def test_an_advisor_gets_the_other_members_services_that_meet_the_case_read_only(
    app: FastAPI, world: NetworkWorld
) -> None:
    advisor = world.ids.members[0]
    await _seed_case(world, advisor)
    async with _client(app) as client:
        response = await client.get(_url(world), headers=_bearer(advisor, (world.ids.network,)))
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    # The advisor's own service is in their own list, not here: the other two members' are.
    assert {o["service_name"] for o in body["options"]} == {
        world.service_name(m) for m in world.ids.members[1:]
    }
    assert body["not_suitable"] == []
    for option in body["options"]:
        assert option["status"] in {"accepting", "limited", "over-capacity"}
        # No member has shared a place or a service line yet (the producer projects none): the row
        # says nothing it cannot stand behind, and the advisor phones to confirm.
        assert (option["travel"], option["position"]) == (None, None)
        assert (option["contact_phone"], option["contact_label"]) == (None, None)
        assert option["criteria_version"] == 3
        assert option["fits"][0] == "Covers this postcode"
    assert body["patient"] == {"lat": 52.0, "lon": -1.4}
    assert (body["not_found"], body["out_of_area"]) == (False, False)
    assert body["system_name"] and body["time_zone"] == "Europe/London"


async def test_a_member_that_shared_a_place_and_a_service_line_is_shown_with_travel_and_the_number(
    app: FastAPI, world: NetworkWorld
) -> None:
    advisor, sharer = world.ids.members[0], world.ids.members[1]
    shared = sample_service_projection(
        source_version=1000, profile=sample_profile(name=world.service_name(sharer))
    )
    result = await world._deliver(
        ProjectionRequested(
            network_id=world.ids.network,
            source_tenant_id=sharer,
            grant_id=f"grant-{sharer}-directory",
            grant_version=1,
            kind=GrantScope.DIRECTORY,
            source_service_id=SERVICE_ID,
            source_version=shared.source_version,
            allowlist_version=PROJECTION_ALLOWLIST_VERSION,
            body=to_body(shared),
            at=READ_AT,
        )
    )
    assert result.reason is None, result
    await _seed_case(world, advisor)
    async with _client(app) as client:
        response = await client.get(_url(world), headers=_bearer(advisor, (world.ids.network,)))
    options = response.json()["options"]
    # The one with a place comes first (travel low end first, none last): an order, not a rank.
    assert [o["service_name"] for o in options] == [
        world.service_name(sharer),
        world.service_name(world.ids.members[2]),
    ]
    assert options[0]["travel"] == {"low_minutes": 12, "high_minutes": 24}
    assert options[0]["position"] == {"lat": 52.0, "lon": -1.5}
    assert (options[0]["contact_label"], options[0]["contact_phone"]) == (
        "Duty desk",
        "0300 123 4567",
    )
    assert options[1]["travel"] is None


async def test_the_answer_names_no_tenant_grant_source_service_or_comment_and_offers_no_booking(
    app: FastAPI, world: NetworkWorld
) -> None:
    advisor = world.ids.members[0]
    await _seed_case(world, advisor)
    async with _client(app) as client:
        response = await client.get(_url(world), headers=_bearer(advisor, (world.ids.network,)))
    text = response.text
    assert not any(t in text for t in (*world.ids.members, world.ids.owner, world.ids.network))
    assert "grant-" not in text and "svc-1" not in text and "crit-1" not in text
    for marks in world.poison.values():
        assert not any(mark in text for mark in marks)
    for word in ("comment", "pending", "reporter", "booking", "request", "tenant"):
        assert word not in {key for row in response.json()["options"] for key in row}


async def test_a_need_the_service_does_not_accept_is_not_suitable_with_the_reason_and_no_need_in_it(
    app: FastAPI, world: NetworkWorld
) -> None:
    advisor = world.ids.members[0]
    await _seed_case(world, advisor, needs=(NeedCategory.IV_THERAPY,))
    async with _client(app) as client:
        response = await client.get(_url(world), headers=_bearer(advisor, (world.ids.network,)))
    body = response.json()
    assert body["options"] == []
    assert {n["reason"] for n in body["not_suitable"]} == {"outside criteria"}
    assert len(body["not_suitable"]) == 2
    assert "iv-therapy" not in response.text and "IV therapy" not in response.text


async def test_a_district_the_network_does_not_cover_is_out_of_area(
    app: FastAPI, world: NetworkWorld
) -> None:
    advisor = world.ids.members[0]
    await _seed_case(world, advisor, postcode="DT9")
    async with _client(app) as client:
        response = await client.get(_url(world), headers=_bearer(advisor, (world.ids.network,)))
    body = response.json()
    assert body["options"] == []
    assert body["out_of_area"] is True
    assert body["not_found"] is True  # the locator does not know DT9 either


async def test_the_case_is_never_written_to_the_network_or_another_tenant(
    app: FastAPI, world: NetworkWorld
) -> None:
    advisor, other = world.ids.members[0], world.ids.members[1]
    await _seed_case(world, advisor)
    async with _client(app) as client:
        await client.get(_url(world), headers=_bearer(advisor, (world.ids.network,)))
    # The case is in the advisor's own tenant and nowhere else: not in another member's.
    with bind_tenant(other):
        async with neo4j_uow_factory(world.driver)() as uow:
            assert await uow.cases.get(CASE_ID) is None
    # And the network's scope holds no tenant data at all (the scope invariants).
    findings = await world.invariants()
    assert all(not rows for rows in findings.values())


async def test_the_advisors_own_audit_says_what_was_shown_with_opaque_references_only(
    app: FastAPI, world: NetworkWorld
) -> None:
    advisor = world.ids.members[0]
    await _seed_case(world, advisor)
    async with _client(app) as client:
        await client.get(_url(world), headers=_bearer(advisor, (world.ids.network,)))
    with bind_tenant(advisor):
        async with neo4j_uow_factory(world.driver)() as uow:
            records = [
                r for r in await uow.audit.records() if r.entry.use_case == "FilterNetworkOptions"
            ]
    assert len(records) == 1
    entry = records[0].entry
    assert entry.action == "R" and entry.entity_ids == (CASE_ID,)
    services = entry.snapshot["services"]
    assert len(services) == 2
    assert {row["shown_as"] for row in services} == {"option"}
    snapshot_text = repr(entry.snapshot)
    assert not any(t in snapshot_text for t in (*world.ids.members, world.ids.owner, "Service m"))


@pytest.mark.parametrize("role", ALL_ROLES)
async def test_role_matrix(app: FastAPI, world: NetworkWorld, role: Role) -> None:
    advisor = world.ids.members[0]
    await _seed_case(world, advisor)
    async with _client(app) as client:
        response = await client.get(
            _url(world), headers=_bearer(advisor, (world.ids.network,), role)
        )
    assert response.status_code == (200 if role in CASE_ROLES else 404), (role, response.text)


async def test_a_tenant_outside_the_network_a_foreign_claim_and_an_unknown_network_are_the_same_404(
    app: FastAPI, world: NetworkWorld
) -> None:
    outsider = world.ids.outsider
    await _seed_case(world, outsider)
    async with _client(app) as client:
        not_member = await client.get(_url(world), headers=_bearer(outsider, (world.ids.network,)))
        unclaimed = await client.get(_url(world), headers=_bearer(world.ids.members[0], ()))
        unknown = await client.get(
            "/network/net-nowhere/options?case=x",
            headers=_bearer(world.ids.members[0], ("net-nowhere",)),
        )
    assert {not_member.status_code, unclaimed.status_code, unknown.status_code} == {404}
    assert not_member.text == unclaimed.text == unknown.text


async def test_another_tenants_case_is_a_404_and_the_viewers_own_is_found_in_their_tenant(
    app: FastAPI, world: NetworkWorld
) -> None:
    a, b = world.ids.members[0], world.ids.members[1]
    await _seed_case(world, a, "case-of-a")
    async with _client(app) as client:
        crossed = await client.get(
            _url(world, "case-of-a"), headers=_bearer(b, (world.ids.network,))
        )
        own = await client.get(_url(world, "case-of-a"), headers=_bearer(a, (world.ids.network,)))
    assert crossed.status_code == 404
    assert own.status_code == 200


async def test_each_member_sees_the_others_and_never_its_own(
    app: FastAPI, world: NetworkWorld
) -> None:
    async with _client(app) as client:
        for index, member in enumerate(world.ids.members):
            await _seed_case(world, member, f"case-m{index}")
            response = await client.get(
                _url(world, f"case-m{index}"), headers=_bearer(member, (world.ids.network,))
            )
            names = {o["service_name"] for o in response.json()["options"]}
            assert names == {world.service_name(m) for m in world.ids.members if m != member}


async def test_a_member_who_left_is_refused_and_their_services_are_no_longer_offered(
    app: FastAPI, world: NetworkWorld
) -> None:
    advisor, leaver = world.ids.members[0], world.ids.members[2]
    await _seed_case(world, advisor)
    async with _client(app) as client:
        before = await client.get(_url(world), headers=_bearer(advisor, (world.ids.network,)))
        await world.leave(leaver)
        gone = await client.get(_url(world), headers=_bearer(leaver, (world.ids.network,)))
        after = await client.get(_url(world), headers=_bearer(advisor, (world.ids.network,)))
    assert len(before.json()["options"]) == 2
    assert gone.status_code == 404
    assert [o["service_name"] for o in after.json()["options"]] == [
        world.service_name(world.ids.members[1])
    ]


async def test_a_closed_case_is_a_409_and_an_incomplete_one_a_400(
    app: FastAPI, world: NetworkWorld
) -> None:
    advisor = world.ids.members[0]
    await _seed_case(world, advisor, "case-incomplete", age_band=None)
    await _seed_case(world, advisor, "case-closed", age_band=AgeBand.A65_79)
    with bind_tenant(advisor):
        async with neo4j_uow_factory(world.driver)() as uow:
            case = await uow.cases.get("case-closed")
            assert case is not None
            await uow.cases.save(case.close(_outcome(), at=READ_AT))
            await uow.commit()
    async with _client(app) as client:
        incomplete = await client.get(
            _url(world, "case-incomplete"), headers=_bearer(advisor, (world.ids.network,))
        )
        closed = await client.get(
            _url(world, "case-closed"), headers=_bearer(advisor, (world.ids.network,))
        )
    assert incomplete.status_code == 400
    assert closed.status_code == 409


async def test_a_malformed_or_missing_case_reference_is_a_400(
    app: FastAPI, world: NetworkWorld
) -> None:
    advisor = world.ids.members[0]
    async with _client(app) as client:
        bad_case = await client.get(
            f"/network/{world.ids.network}/options?case=../x",
            headers=_bearer(advisor, (world.ids.network,)),
        )
        no_case = await client.get(
            f"/network/{world.ids.network}/options", headers=_bearer(advisor, (world.ids.network,))
        )
    assert bad_case.status_code == 400 and no_case.status_code == 400


async def test_a_process_with_no_options_service_fails_closed(
    app: FastAPI, world: NetworkWorld
) -> None:
    advisor = world.ids.members[0]
    await _seed_case(world, advisor)
    services = app.state.network_services
    app.state.network_services = replace(services, options=None)
    try:
        async with _client(app) as client:
            response = await client.get(_url(world), headers=_bearer(advisor, (world.ids.network,)))
        assert response.status_code == 500
    finally:
        app.state.network_services = services


def _outcome() -> Any:
    from diucs.domain.codes import Outcome

    return Outcome.NO_SERVICE_FITS
