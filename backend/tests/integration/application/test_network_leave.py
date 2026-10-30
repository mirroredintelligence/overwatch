"""Leave and grant-end semantics on a real Neo4j (TEN-056, DEC-132 items 3 and 6, hazard H-N05).

The world is the one of TEN-060: an owner, three members that hold a service with the same ids, a
network, every grant approved and every listing admitted. The producer and the apply step run as the
workers do. These tests end things through the product's own use cases (`EndProjections`,
`ReconcileProjection`, `RunProjectionHeartbeat`) and look at the three kinds of place: the network
scope (live and history), the registry, and the member's own scope.
"""

import asyncio
import os
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest
import pytest_asyncio
from neo4j import AsyncDriver

from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.outbound.graph_store.unit_of_work import neo4j_uow_factory
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.application.ports.outbound.projection import ProjectionEndReason
from diucs.application.tenancy import bind_tenant
from diucs.application.use_cases.apply_projection import ApplyOutcome
from diucs.application.use_cases.network_leave import EndProjections
from diucs.application.use_cases.project_network import ProjectNetwork
from diucs.application.use_cases.projection_boundaries import (
    RunProjectionHeartbeat,
    RunProjectionHeartbeatCommand,
    ensure_projection_schedule,
)
from diucs.application.use_cases.projection_reconcile import ReconcileProjection
from diucs.application.work import WorkKind
from diucs.domain.events import ProjectionRejectReason
from diucs.domain.model.network import (
    GrantEndReason,
    GrantScope,
    GrantStatus,
    MembershipEndReason,
    MembershipStatus,
    end_membership,
)
from diucs.domain.rules.grant import end_grant, lapse_grants_for_member
from tests.support.network_samples import ACCOUNT_B, NOW
from tests.support.network_world import NetworkWorld, world_ids
from tests.support.tenancy import RunIdentity
from tests.support.uow import ensure_audit_heads

pytestmark = pytest.mark.asyncio(loop_scope="session")

AT = NOW + timedelta(minutes=30)


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
    yield built
    await built.cleanup()


class _Rig:
    def __init__(self, world: NetworkWorld) -> None:
        self.world = world
        clock = FixedClock(AT)
        self.clock = clock
        self.ends = EndProjections(
            lambda: _network_unit(world),  # type: ignore[arg-type,return-value]
            world.registry,
            clock,
        )
        self.reconcile = ReconcileProjection(
            lambda: _network_unit(world, read_only=True),  # type: ignore[arg-type,return-value]
            self.ends,
            world.registry,
            clock,
        )

    async def leave_in_the_registry(self, member: str) -> None:
        """Only the registry's half of a leave: the membership ends, the grants lapse."""
        registry = self.world.registry
        row = await registry.active_membership(self.world.ids.network, member)
        assert row is not None
        left = end_membership(self.world.network, row, reason=MembershipEndReason.LEFT, now=NOW)
        await registry.save_membership(left, expected_status=MembershipStatus.ACTIVE)
        for grant in lapse_grants_for_member(await registry.grants_of(member), row, now=NOW):
            await registry.save_grant(grant, expected_status=GrantStatus.APPROVED)

    async def end_grant_in_the_registry(self, member: str, scope: GrantScope) -> None:
        registry = self.world.registry
        grant = await registry.get_grant(f"grant-{member}-{scope.value}")
        assert grant is not None
        ended = end_grant(grant, by_tenant_id=member, account_ref=ACCOUNT_B, now=NOW)
        await registry.save_grant(ended, expected_status=GrantStatus.APPROVED)


def _network_unit(world: NetworkWorld, *, read_only: bool = False) -> Any:
    from diucs.adapters.outbound.graph_store.unit_of_work import Neo4jUnitOfWork

    return Neo4jUnitOfWork(world.driver, read_only=read_only)


async def _live_and_history(world: NetworkWorld, member: str) -> tuple[int, int, set[Any]]:
    live = await world.view()
    every = await world.view(live_only=False)
    mine_live = sum(1 for rows in live for r in rows if r.source_tenant_id == member)
    mine_all = [r for rows in every for r in rows if r.source_tenant_id == member]
    return mine_live, len(mine_all), {r.end_reason for r in mine_all}


async def test_a_member_that_left_is_ended_marked_with_the_date_and_kept_in_history(
    world: NetworkWorld,
) -> None:
    await world.run_projector()
    member, other = world.ids.members[0], world.ids.members[1]
    before_live, before_all, _ = await _live_and_history(world, member)
    assert before_live == before_all > 0
    rig = _Rig(world)
    await rig.leave_in_the_registry(member)
    result = await rig.ends.end_member(world.ids.network, member, at=NOW)
    assert result.sources_ended == 3
    assert result.rows_marked >= before_live  # the service's windows and place are marked too
    live, every, reasons = await _live_and_history(world, member)
    assert (live, every) == (0, before_all)
    assert reasons == {ProjectionEndReason.LEFT}
    # the other members keep every live row
    other_live, _, _ = await _live_and_history(world, other)
    assert other_live > 0
    services = (await world.view(live_only=False))[0]
    assert {r.ended_at for r in services if r.source_tenant_id == member} == {NOW}


async def test_ending_one_grant_ends_that_kind_and_leaves_the_others(world: NetworkWorld) -> None:
    await world.run_projector()
    member = world.ids.members[0]
    rig = _Rig(world)
    await rig.end_grant_in_the_registry(member, GrantScope.CAPACITY)
    result = await rig.ends.end_grant(
        world.ids.network, member, GrantScope.CAPACITY, reason=GrantEndReason.ENDED, at=NOW
    )
    assert result.sources_ended == 1 and result.rows_marked >= 1
    services, capacities, criteria = await world.view()
    assert [r for r in capacities if r.source_tenant_id == member] == []
    assert any(r.source_tenant_id == member for r in services)
    assert any(r.source_tenant_id == member for r in criteria)
    ended = (await world.view(live_only=False))[1]
    [row] = [r for r in ended if r.source_tenant_id == member]
    assert row.end_reason is ProjectionEndReason.GRANT_ENDED


async def test_a_projection_that_arrives_after_the_end_writes_nothing(world: NetworkWorld) -> None:
    member = world.ids.members[0]
    [capacity] = [r for r in await world.produce_as(member) if r.kind is GrantScope.CAPACITY]
    rig = _Rig(world)
    await rig.end_grant_in_the_registry(member, GrantScope.CAPACITY)
    await rig.ends.end_grant(
        world.ids.network, member, GrantScope.CAPACITY, reason=GrantEndReason.ENDED, at=NOW
    )
    late = await world._deliver(capacity)
    assert (late.outcome, late.reason) == (
        ApplyOutcome.REJECTED,
        ProjectionRejectReason.GRANT_NOT_EFFECTIVE,
    )
    assert [r for r in (await world.view(live_only=False))[1] if r.source_tenant_id == member] == []


async def test_a_racing_end_and_projection_leave_no_live_row(world: NetworkWorld) -> None:
    """The registry is ended first (it is the gate). Whichever of the end and the apply step runs
    first, the result is the same: nothing of the member's capacity is live."""
    members = world.ids.members
    rig = _Rig(world)
    requests = {
        m: [r for r in await world.produce_as(m) if r.kind is GrantScope.CAPACITY] for m in members
    }
    for member in members:
        await rig.end_grant_in_the_registry(member, GrantScope.CAPACITY)
    jobs: list[Any] = []
    for member in members:
        jobs.append(world._deliver(requests[member][0]))
        jobs.append(
            rig.ends.end_grant(
                world.ids.network,
                member,
                GrantScope.CAPACITY,
                reason=GrantEndReason.ENDED,
                at=NOW,
            )
        )
    await asyncio.gather(*jobs)
    live = (await world.view())[1]
    assert live == []


async def test_a_lost_end_is_healed_by_the_reconciliation(world: NetworkWorld) -> None:
    await world.run_projector()
    member = world.ids.members[2]
    rig = _Rig(world)
    await rig.leave_in_the_registry(member)  # the network step never ran
    assert (await _live_and_history(world, member))[0] > 0
    result = await rig.reconcile.member(world.ids.network, member)
    assert result.sources_ended == 3 and result.rows_marked > 0
    assert (await _live_and_history(world, member))[0] == 0
    again = await rig.reconcile.member(world.ids.network, member)
    assert (again.sources_ended, again.rows_marked) == (0, 0)


async def test_a_member_whose_grants_stand_is_left_alone_by_the_reconciliation(
    world: NetworkWorld,
) -> None:
    await world.run_projector()
    member = world.ids.members[0]
    before = await _live_and_history(world, member)
    result = await _Rig(world).reconcile.member(world.ids.network, member)
    assert (result.sources_ended, result.rows_marked) == (0, 0)
    assert await _live_and_history(world, member) == before


async def test_the_heartbeat_projects_reconciles_and_schedules_its_own_next_job(
    world: NetworkWorld, harness_driver: AsyncDriver
) -> None:
    member = world.ids.members[0]
    await ensure_audit_heads(harness_driver, member)
    rig = _Rig(world)
    clock = FixedClock(NOW)
    factory = neo4j_uow_factory(harness_driver)
    producer = ProjectNetwork(
        neo4j_uow_factory(harness_driver, read_only=True),
        world.registry,
        world._recorder,
        clock,
    )

    class _Ids:
        n = 0

        def new_id(self) -> str:
            _Ids.n += 1
            return f"hb-{world.ids.network}-{_Ids.n}"

    ids = _Ids()
    beat = RunProjectionHeartbeat(factory, ids, clock, world.registry, producer, rig.reconcile)
    with bind_tenant(member):
        assert await ensure_projection_schedule(factory, ids, clock) is True
        assert await ensure_projection_schedule(factory, ids, clock) is False
        world._recorder.sent.clear()
        first = await beat.execute(RunProjectionHeartbeatCommand("hb-work-1"))
        again = await beat.execute(RunProjectionHeartbeatCommand("hb-work-1"))
        async with factory() as uow:
            works = await uow.scheduled_work.for_about(member, WorkKind.PROJECTION_HEARTBEAT)
    assert first.requested == 3 and first.next_due is not None and not first.replayed
    assert again.replayed
    assert len(works) == 2  # the first job (ensure) and the one the heartbeat scheduled
    capacity = [r for r in world._recorder.sent if r.kind is GrantScope.CAPACITY]
    assert capacity and capacity[0].body["valid_until"] is not None
    assert replace(first, next_due=None).requested == 3
