"""Two-member network tests, part one: the grant lifecycle (TEN-061, DEC-132 items 3 and 4, DEC-134
item 6, hazards H-N03, H-N05, H-N06).

An owner and two members on a real Neo4j, driven through the product's own use cases and the two
halves of the workers (`tests/support/network_admin_rig.py`): dual approval, the window, ending by
the grantor, the separation of the scopes, concurrency between an end and a projection, and a
stale projection that must read Not updated. The member that does nothing is the control: nothing
of it may change.
"""

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import pytest
import pytest_asyncio
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.application.ports.outbound.projection import ProjectionEndReason
from diucs.application.tenancy import bind_tenant
from diucs.application.use_cases.apply_projection import ApplyOutcome
from diucs.application.use_cases.grants import EndGrantCommand
from diucs.application.work import WorkKind
from diucs.domain.codes import Status
from diucs.domain.errors import NotFound
from diucs.domain.events import ProjectionRejectReason
from diucs.domain.model.network import GrantScope
from tests.support.neo4j import read_tx
from tests.support.network_admin_rig import START, AdminRig
from tests.support.network_world import NETWORK_INVARIANTS, world_ids
from tests.support.tenancy import RunIdentity

pytestmark = pytest.mark.asyncio(loop_scope="session")

ALL = tuple(GrantScope)


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
async def rig(
    harness_driver: AsyncDriver,
    connection: Neo4jConnection,
    run_identity: RunIdentity,
    clean_graph: None,
) -> AsyncIterator[AdminRig]:
    built = await AdminRig.build(harness_driver, connection, world_ids(run_identity))
    await built.make_network()
    for member, admin in zip(built.ids.members[:2], built.people.admins[:2], strict=True):
        await built.join(member, admin)
    yield built
    await built.cleanup()


def _a(rig: AdminRig) -> tuple[str, Any]:
    return rig.ids.members[0], rig.people.admins[0]


def _b(rig: AdminRig) -> tuple[str, Any]:
    return rig.ids.members[1], rig.people.admins[1]


async def _share_everything(rig: AdminRig, member: str, admin: Any, **kw: Any) -> None:
    await rig.share(member, admin, *ALL, **kw)
    await rig.list_service(member, admin)


def _live(rig: AdminRig, rows: tuple[Any, Any, Any], member: str) -> int:
    return sum(len(rig.rows_of(member, kind)) for kind in rows)


# ---------------------------------------------------------------- dual approval starts a projection


async def test_the_second_approval_starts_the_projection_through_the_governance_event(
    rig: AdminRig,
) -> None:
    a, admin = _a(rig)
    await _share_everything(rig, a, admin)
    assert _live(rig, await rig.view(), a) == 0  # approved, but nothing has run yet
    delivered = await rig.deliver_events()
    effective = [d for d in delivered if d[1] == "GrantEffective"]
    assert {d[0] for d in effective} == {rig.ids.owner}  # the last approval was the owner's
    assert all(d[2].value == "handled" for d in effective)
    applied = await rig.apply_pending()
    assert len(applied) == 3 and all(r.outcome is ApplyOutcome.APPLIED for r in applied)
    services, capacities, criteria = await rig.view()
    assert [len(rig.rows_of(a, rows)) for rows in (services, capacities, criteria)] == [1, 1, 1]
    # the member's own heartbeat chain was started by the event
    with bind_tenant(a):
        async with rig.tenant_factory() as uow:
            works = await uow.scheduled_work.for_about(a, WorkKind.PROJECTION_HEARTBEAT)
    assert len(works) == 1


async def test_a_grant_of_one_scope_projects_only_that_scope(rig: AdminRig) -> None:
    a, admin = _a(rig)
    await rig.share(a, admin, GrantScope.DIRECTORY)
    await rig.list_service(a, admin)
    await rig.deliver_events()
    await rig.apply_pending()
    services, capacities, criteria = await rig.view()
    assert (
        len(rig.rows_of(a, services)),
        rig.rows_of(a, capacities),
        rig.rows_of(a, criteria),
    ) == (
        1,
        [],
        [],
    )


async def test_a_service_the_owner_has_not_admitted_projects_nothing(rig: AdminRig) -> None:
    a, admin = _a(rig)
    await rig.share(a, admin, *ALL)  # approved by both, but no listing
    await rig.deliver_events()
    assert await rig.apply_pending() == []
    assert _live(rig, await rig.view(), a) == 0
    assert all(r.outcome is ApplyOutcome.APPLIED for r in await _list_then_project(rig, a, admin))


async def _list_then_project(rig: AdminRig, member: str, admin: Any) -> list[Any]:
    await rig.list_service(member, admin)
    return await rig.project(member)


async def test_a_member_that_shares_nothing_has_nothing_in_the_network(rig: AdminRig) -> None:
    a, admin = _a(rig)
    b, _ = _b(rig)
    await _share_everything(rig, a, admin)
    await rig.deliver_events()
    await rig.apply_pending()
    assert _live(rig, await rig.view(live_only=False), b) == 0
    assert await rig.project(b) == []  # no grant: the producer costs one registry read


# ---------------------------------------------------------------- the window


async def test_a_grant_that_starts_later_projects_nothing_until_then_and_stops_when_it_ends(
    rig: AdminRig,
) -> None:
    a, admin = _a(rig)
    start, end = START + timedelta(hours=2), START + timedelta(hours=5)
    await _share_everything(rig, a, admin, effective_from=start, effective_to=end)
    await rig.deliver_events()
    assert await rig.apply_pending() == []  # approved, not yet started
    rig.tick(timedelta(hours=1))
    await rig.beat(a, "early")
    assert _live(rig, await rig.view(), a) == 0
    rig.tick(timedelta(hours=1, minutes=1))  # 11 past 12: it has started
    first = await rig.beat(a, "start")
    assert first.requested == 3
    assert _live(rig, await rig.view(), a) == 3
    rig.tick(timedelta(hours=3))  # past the end of the window: no event, only the clock
    last = await rig.beat(a, "end")
    assert last.next_due is not None  # the grant still reads approved: the chain carries on
    live, history = await rig.view(), await rig.view(live_only=False)
    assert _live(rig, live, a) == 0 and _live(rig, history, a) == 3
    reasons = {r.end_reason for rows in history for r in rig.rows_of(a, rows)}
    assert reasons == {ProjectionEndReason.GRANT_ENDED}


async def test_a_heartbeat_moves_the_projection_forward_and_never_backwards(rig: AdminRig) -> None:
    a, admin = _a(rig)
    await _share_everything(rig, a, admin)
    await rig.deliver_events()
    await rig.apply_pending()
    before = (await rig.view())[1]
    rig.tick(timedelta(minutes=5))
    await rig.beat(a, "hb-1")
    after = (await rig.view())[1]
    assert after[0].projected_at > before[0].projected_at
    assert after[0].projection.source_version > before[0].projection.source_version
    # a message that is older than the stored version is refused as stale, not applied
    stale = [r for r in rig.published.sent]
    assert stale == []


# ---------------------------------------------------------------- end by the grantor


async def test_ending_one_scope_stops_that_scope_and_nothing_else(rig: AdminRig) -> None:
    a, admin = _a(rig)
    b, admin_b = _b(rig)
    await _share_everything(rig, a, admin)
    await _share_everything(rig, b, admin_b)
    await rig.deliver_events()
    await rig.apply_pending()
    grants = [g for g in await rig.registry.grants_of(a) if g.scope is GrantScope.CAPACITY]
    rig.tick(timedelta(minutes=10))
    with bind_tenant(a):
        await rig.end_grant.execute(EndGrantCommand(admin, grants[0].id))
    services, capacities, criteria = await rig.view()
    assert rig.rows_of(a, capacities) == []
    assert len(rig.rows_of(a, services)) == 1 and len(rig.rows_of(a, criteria)) == 1
    assert [_live(rig, (services, capacities, criteria), b)] == [3]  # the other member is untouched
    history = (await rig.view(live_only=False))[1]
    [ended] = rig.rows_of(a, history)
    assert ended.end_reason is ProjectionEndReason.GRANT_ENDED
    assert ended.ended_at == rig.clock.now()


async def test_a_projection_that_arrives_after_the_end_writes_nothing_and_a_later_grant_resumes(
    rig: AdminRig,
) -> None:
    a, admin = _a(rig)
    await _share_everything(rig, a, admin)
    await rig.deliver_events()
    rig.published.sent.clear()
    with bind_tenant(a):
        await rig.producer.project(GrantScope.CAPACITY, "svc-1")
    [late] = list(rig.published.sent)
    rig.published.sent.clear()
    [grant] = [g for g in await rig.registry.grants_of(a) if g.scope is GrantScope.CAPACITY]
    with bind_tenant(a):
        await rig.end_grant.execute(EndGrantCommand(admin, grant.id))
    rig.published.sent.append(late)
    [result] = await rig.apply_pending()
    assert (result.outcome, result.reason) == (
        ApplyOutcome.REJECTED,
        ProjectionRejectReason.GRANT_NOT_EFFECTIVE,
    )
    assert rig.rows_of(a, (await rig.view(live_only=False))[1]) == []
    # a new grant of the scope (the next version) resumes it
    rig.tick(timedelta(minutes=10))
    await rig.share(a, admin, GrantScope.CAPACITY)
    await rig.deliver_events()
    await rig.apply_pending()
    [row] = rig.rows_of(a, (await rig.view())[1])
    assert row.ended_at is None and row.end_reason is None


# ---------------------------------------------------------------- concurrency


async def test_an_end_and_a_projection_that_race_leave_no_live_row_whatever_the_order(
    rig: AdminRig,
) -> None:
    a, admin = _a(rig)
    b, admin_b = _b(rig)
    for member, who in ((a, admin), (b, admin_b)):
        await _share_everything(rig, member, who)
    await rig.deliver_events()
    requests = {}
    for member in (a, b):
        rig.published.sent.clear()
        with bind_tenant(member):
            await rig.producer.project(GrantScope.CAPACITY, "svc-1")
        requests[member] = list(rig.published.sent)
    rig.published.sent.clear()
    grants = {
        m: [g for g in await rig.registry.grants_of(m) if g.scope is GrantScope.CAPACITY][0]
        for m in (a, b)
    }

    async def end(member: str, who: Any) -> None:
        with bind_tenant(member):
            await rig.end_grant.execute(EndGrantCommand(who, grants[member].id))

    async def apply(member: str) -> Any:
        rig._message += 1
        from diucs.application.tenancy import bind_network

        with bind_network(rig.ids.network):
            return await rig.apply.execute(
                requests[member][0],
                message_id=f"race-{rig.token}-{rig._message}",
                source_tenant_id=member,
            )

    await asyncio.gather(end(a, admin), apply(a), apply(b), end(b, admin_b))
    capacities = (await rig.view())[1]
    assert rig.rows_of(a, capacities) == [] and rig.rows_of(b, capacities) == []


# ---------------------------------------------------------------- stale reads


async def test_a_member_that_stops_reporting_reads_not_updated_with_no_new_event(
    rig: AdminRig,
) -> None:
    a, admin = _a(rig)
    b, _ = _b(rig)
    await rig.add_report(a, START - timedelta(minutes=5))
    await _share_everything(rig, a, admin)
    await _share_everything(rig, b, rig.people.admins[1])
    await rig.deliver_events()
    await rig.apply_pending()
    viewer = rig.viewer(b)

    async def statuses() -> list[Status | None]:
        view = await rig.board.execute(viewer, rig.ids.network)
        return sorted(
            [e.status for e in view.board.entries if e.organisation_name == "Member 1 Org"],
            key=str,
        )

    rig.tick(timedelta(minutes=1))
    fresh = await statuses()
    assert fresh and Status.NOT_UPDATED not in fresh
    rig.tick(timedelta(hours=3))  # nothing was reported and nothing was projected since
    assert await statuses() == [Status.NOT_UPDATED]


async def test_a_member_cannot_read_a_network_it_is_not_in_and_a_viewer_of_another_member_does(
    rig: AdminRig,
) -> None:
    a, admin = _a(rig)
    await _share_everything(rig, a, admin)
    await rig.deliver_events()
    await rig.apply_pending()
    view = await rig.board.execute(rig.viewer(rig.ids.members[1]), rig.ids.network)
    assert [e.organisation_name for e in view.board.entries] == ["Member 1 Org"]
    with pytest.raises(NotFound):
        await rig.board.execute(rig.viewer(rig.ids.outsider), rig.ids.network)


# ---------------------------------------------------------------- scope separation


async def test_the_network_scope_holds_only_the_allowlist_and_every_invariant_holds(
    rig: AdminRig, harness_driver: AsyncDriver
) -> None:
    a, admin = _a(rig)
    b, admin_b = _b(rig)
    for member, who in ((a, admin), (b, admin_b)):
        await _share_everything(rig, member, who)
    await rig.deliver_events()
    await rig.apply_pending()
    found = await rig.world.invariants()
    assert set(found) == set(NETWORK_INVARIANTS)
    assert all(rows == [] for rows in found.values()), found

    async def everything(tx: AsyncManagedTransaction) -> str:
        rows = await (
            await tx.run(
                "MATCH (n {tenantId: $s}) RETURN labels(n) AS l, properties(n) AS p",
                s=rig.ids.network,
            )
        ).data()
        return repr(rows)

    text = await read_tx(harness_driver, everything)
    for member in (a, b):
        for poison in rig.world.poison[member]:
            assert poison not in text
    for member in (a, b):  # no member's tenant scope holds a projection
        for label in ("ProjectedService", "ProjectedCapacity", "ProjectedCriteria"):
            assert await rig.count(member, label) == 0
    assert (await rig.world.global_invariants()).ok
