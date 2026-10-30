"""One unit of work, one scope, over three kinds of scope (TEN-062, DEC-130 item 7, DEC-132 item 4,
DEC-540).

A unit of work binds exactly one scope. The tests show: a tenant unit cannot reach the network
repositories (the projection writer, the network reader, the samples) and a network unit cannot
reach a tenant repository, each refused before any Cypher is sent; a unit cannot be opened inside
another, in either direction; the projection is two units that are never nested (the producer in the
member's scope, the apply step in the network's) and a failure between them leaves no partial
projection, a retry converges and a replay changes nothing; the apply step refuses a binding that is
not the network the message names; and a request binds its scope for its own task only: nothing it
bound is left behind for the next request, a network route does not leave a network scope bound and
a tenant route afterwards still reads only its tenant.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
from neo4j import AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.unit_of_work import Neo4jUnitOfWork
from diucs.application.ports.outbound.projection import GrantRef
from diucs.application.tenancy import (
    ReadOnlyUnitWrite,
    ScopeKindMismatch,
    UnitOfWorkAlreadyOpen,
    bind_network,
    bind_tenant,
    current_scope_or_none,
)
from diucs.application.use_cases.apply_projection import ApplyOutcome, ProjectionMismatch
from diucs.domain.codes import Role
from diucs.domain.model.network import GrantScope
from diucs.domain.rules.network_sample import READINGS, NetworkSample
from diucs.domain.rules.pressure import Pressure
from tests.support import network_fixtures
from tests.support.neo4j import read_tx
from tests.support.network_fixtures import NetApp, bearer, client_of
from tests.support.network_world import NetworkWorld
from tests.support.projection_samples import (
    sample_capacity_projection,
    sample_service_projection,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")

bare_world = network_fixtures.bare_world
connection = network_fixtures.connection
world = network_fixtures.world
net_app = network_fixtures.net_app

HOUR = datetime(2026, 10, 26, 9, 0, tzinfo=UTC)
GRANT = GrantRef("grant-x-1", 1)


def _sample() -> NetworkSample:
    return NetworkSample(
        hour=HOUR,
        at=HOUR,
        counts=tuple((status, 1) for status in READINGS),
        unavailable=0,
        organisations=3,
        pressure=Pressure.NORMAL,
    )


async def _network_rows(world: NetworkWorld) -> int:
    async def count(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        result = await tx.run(
            "MATCH (n {tenantId: $net}) WHERE any(l IN labels(n) WHERE l STARTS WITH 'Projected') "
            "RETURN count(n) AS n",
            net=world.ids.network,
        )
        return await result.data()

    return int((await read_tx(world.driver, count))[0]["n"])


# ------------------------------------------------------------------ a unit holds one scope


async def test_a_tenant_unit_cannot_reach_any_network_repository(
    world: NetworkWorld,
) -> None:
    member = world.ids.members[0]
    with bind_tenant(member):
        async with Neo4jUnitOfWork(world.driver) as uow:
            with pytest.raises(ScopeKindMismatch):
                await uow.projections.open_source(member, GrantScope.CAPACITY, GRANT)
            with pytest.raises(ScopeKindMismatch):
                await uow.projections.upsert_capacity(
                    member, sample_capacity_projection(), grant=GRANT, projected_at=HOUR
                )
            with pytest.raises(ScopeKindMismatch):
                await uow.network_view.services()
            with pytest.raises(ScopeKindMismatch):
                await uow.network_view.capacities()
            with pytest.raises(ScopeKindMismatch):
                await uow.network_samples.record(_sample())
            with pytest.raises(ScopeKindMismatch):
                await uow.network_samples.between(HOUR, HOUR)


async def test_a_network_unit_cannot_reach_a_tenant_repository(world: NetworkWorld) -> None:
    with bind_network(world.ids.network):
        async with Neo4jUnitOfWork(world.driver) as uow:
            with pytest.raises(ScopeKindMismatch):
                await uow.services.get("svc-1")
            with pytest.raises(ScopeKindMismatch):
                await uow.services.list_active()
            with pytest.raises(ScopeKindMismatch):
                await uow.capacity.latest("svc-1")
            with pytest.raises(ScopeKindMismatch):
                await uow.devices.peek("screen-1")
            with pytest.raises(ScopeKindMismatch):
                await uow.criteria.current_for_service("svc-1")


async def test_a_read_only_network_unit_reads_and_cannot_write_a_sample_or_a_projection(
    world: NetworkWorld,
) -> None:
    member = world.ids.members[0]
    with bind_network(world.ids.network):
        async with Neo4jUnitOfWork(world.driver, read_only=True) as uow:
            assert len(await uow.network_view.services()) == 3
            with pytest.raises(ReadOnlyUnitWrite):
                await uow.network_samples.record(_sample())
            with pytest.raises(ReadOnlyUnitWrite):
                await uow.projections.upsert_service(
                    member, sample_service_projection(), grant=GRANT, projected_at=HOUR
                )


async def test_a_unit_cannot_be_opened_inside_another_in_either_direction(
    world: NetworkWorld,
) -> None:
    member = world.ids.members[0]
    with bind_tenant(member):
        async with Neo4jUnitOfWork(world.driver, read_only=True):
            with bind_network(world.ids.network), pytest.raises(UnitOfWorkAlreadyOpen):
                async with Neo4jUnitOfWork(world.driver):
                    pass
    with bind_network(world.ids.network):
        async with Neo4jUnitOfWork(world.driver, read_only=True):
            with bind_tenant(member), pytest.raises(UnitOfWorkAlreadyOpen):
                async with Neo4jUnitOfWork(world.driver):
                    pass


async def test_a_unit_keeps_the_scope_it_opened_under_even_if_the_binding_moves(
    world: NetworkWorld,
) -> None:
    member = world.ids.members[0]
    with bind_network(world.ids.network):
        async with Neo4jUnitOfWork(world.driver, read_only=True) as uow:
            with bind_tenant(member):
                rows = await uow.network_view.services()
    assert len(rows) == 3


# ------------------------------------------------------------------ two units, never nested


async def test_the_producer_reads_in_the_members_scope_and_the_apply_writes_in_the_networks(
    bare_world: NetworkWorld,
) -> None:
    member = bare_world.ids.members[0]
    baseline = current_scope_or_none()
    requests = await bare_world.produce_as(member)
    assert {r.kind for r in requests} == set(GrantScope)
    assert {r.network_id for r in requests} == {bare_world.ids.network}
    assert {r.source_tenant_id for r in requests} == {member}
    assert current_scope_or_none() == baseline, "the producer left a scope bound"


async def test_a_failure_between_the_two_units_leaves_nothing_half_projected(
    bare_world: NetworkWorld,
) -> None:
    member = bare_world.ids.members[0]
    before = await _network_rows(bare_world)
    requests = await bare_world.produce_as(member)
    assert await _network_rows(bare_world) == before
    # the producer's unit has finished and the message is in flight: the apply step never ran
    # (a crash, a dead consumer). Nothing of the member is in the network yet.
    results = [await bare_world._deliver(request) for request in requests]
    assert {r.outcome for r in results} == {ApplyOutcome.APPLIED}
    # a service, its location and opening windows, a capacity row and a criteria row
    assert before == 0 and await _network_rows(bare_world) >= 4


async def test_a_retry_after_the_failure_converges_and_a_replay_changes_nothing(
    bare_world: NetworkWorld,
) -> None:
    member = bare_world.ids.members[2]
    first = await bare_world.produce_as(member)
    await bare_world._deliver(first[0])  # only one of the messages arrived before the crash
    partial = await _network_rows(bare_world)
    again = await bare_world.produce_as(member)  # the retry produces the same messages
    for request in again:
        await bare_world._deliver(request)
    converged = await _network_rows(bare_world)
    assert converged > 0
    for request in again:
        await bare_world._deliver(request)
    assert await _network_rows(bare_world) == converged
    assert partial <= converged


async def test_the_apply_step_refuses_a_binding_that_is_not_the_network_the_message_names(
    bare_world: NetworkWorld,
) -> None:
    member = bare_world.ids.members[0]
    [request, *_] = await bare_world.produce_as(member)
    before = await _network_rows(bare_world)
    with bind_tenant(member), pytest.raises(ProjectionMismatch):
        await bare_world._apply.execute(request, message_id="m-1", source_tenant_id=member)
    with bind_network(bare_world.ids.other_network), pytest.raises(ProjectionMismatch):
        await bare_world._apply.execute(request, message_id="m-2", source_tenant_id=member)
    with bind_network(bare_world.ids.network), pytest.raises(ProjectionMismatch):
        await bare_world._apply.execute(
            request, message_id="m-3", source_tenant_id=bare_world.ids.members[1]
        )
    assert await _network_rows(bare_world) == before


# ------------------------------------------------------------------ a request binds for itself


async def test_a_network_route_leaves_no_scope_bound_in_the_callers_task(
    net_app: NetApp, world: NetworkWorld
) -> None:
    member = world.ids.members[0]
    network = world.ids.network
    baseline = current_scope_or_none()
    with bind_tenant(member):
        async with client_of(net_app) as client:
            board = await client.get(
                f"/network/{network}/board", headers=bearer(member, Role.ADVISOR, (network,))
            )
        scope = current_scope_or_none()
    assert board.status_code == 200
    assert scope is not None and scope.value == member and current_scope_or_none() == baseline


async def test_a_tenant_route_after_a_network_route_reads_its_own_tenant_only(
    net_app: NetApp, world: NetworkWorld
) -> None:
    first, second = world.ids.members[:2]
    network = world.ids.network
    baseline = current_scope_or_none()
    async with client_of(net_app) as client:
        for tenant in (first, second, first):
            await client.get(
                f"/network/{network}/board", headers=bearer(tenant, Role.ADVISOR, (network,))
            )
            own = await client.get(
                "/fhir/HealthcareService/svc-1", headers=bearer(tenant, Role.ADVISOR)
            )
            assert own.status_code == 200
            assert world.service_name(tenant) in own.text
            other = second if tenant == first else first
            assert world.service_name(other) not in own.text
    assert current_scope_or_none() == baseline


async def test_the_scope_of_a_failed_network_request_is_not_left_bound_either(
    net_app: NetApp, world: NetworkWorld
) -> None:
    network = world.ids.network
    baseline = current_scope_or_none()
    async with client_of(net_app) as client:
        refused = await client.get(
            f"/network/{network}/board",
            headers=bearer(world.ids.outsider, Role.ADVISOR, (network,)),
        )
    assert refused.status_code == 404
    assert current_scope_or_none() == baseline
