"""Two-member network tests, part two: leave, history and re-join (TEN-061, DEC-132 items 4 and 6,
hazards H-N05 and H-N08).

When a member leaves, or the owner removes it, its membership closes, its grants lapse, its
listings are withdrawn and its rows in the network scope end with the date: the live reads no
longer show it, the history reads still do, and nothing is deleted. A member that joins again is a
new membership with new grants (a closed row is never reopened) and its rows are live again. Every
step is in the network's audit chain, which verifies.
"""

import os
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import pytest
import pytest_asyncio
from neo4j import AsyncDriver

from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.outbound.graph_store.unit_of_work import neo4j_uow_factory
from diucs.application.ports.outbound.projection import ProjectionEndReason
from diucs.application.tenancy import bind_tenant
from diucs.application.use_cases.membership import (
    AcceptMembershipCommand,
    InviteMemberCommand,
    LeaveNetworkCommand,
    RemoveMemberCommand,
)
from diucs.application.use_cases.query_network_directory import QueryNetworkDirectory
from diucs.domain.errors import NotFound
from diucs.domain.model.network import (
    GrantScope,
    GrantStatus,
    ListingStatus,
    MembershipEndReason,
    MembershipStatus,
)
from tests.support.network_admin_rig import AdminRig
from tests.support.network_world import world_ids
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
        await built.share(member, admin, *ALL)
        await built.list_service(member, admin)
    await built.deliver_events()
    await built.apply_pending()
    yield built
    await built.cleanup()


def _a(rig: AdminRig) -> tuple[str, Any]:
    return rig.ids.members[0], rig.people.admins[0]


def _b(rig: AdminRig) -> tuple[str, Any]:
    return rig.ids.members[1], rig.people.admins[1]


def _directory(rig: AdminRig, driver: AsyncDriver) -> QueryNetworkDirectory:
    return QueryNetworkDirectory(
        neo4j_uow_factory(driver, clock=rig.clock, read_only=True), rig.access, rig.clock
    )


def _live(rig: AdminRig, rows: tuple[Any, Any, Any], member: str) -> int:
    return sum(len(rig.rows_of(member, kind)) for kind in rows)


async def test_a_member_that_leaves_disappears_from_the_live_reads_and_stays_in_the_history(
    rig: AdminRig, harness_driver: AsyncDriver
) -> None:
    a, admin = _a(rig)
    b, _ = _b(rig)
    viewer = rig.viewer(b)
    reader = _directory(rig, harness_driver)
    assert len((await reader.execute(viewer, rig.ids.network)).entries) == 2
    rig.tick(timedelta(hours=1))
    left_at = rig.clock.now()
    with bind_tenant(a):
        await rig.leave.execute(LeaveNetworkCommand(admin, rig.ids.network))
    live = await reader.execute(viewer, rig.ids.network)
    assert [e.organisation_name for e in live.entries] == ["Member 2 Org"]
    history = await reader.execute(viewer, rig.ids.network, history=True)
    gone = [e for e in history.entries if e.organisation_name == "Member 1 Org"]
    assert len(gone) == 1
    assert (gone[0].ended_at, gone[0].end_reason) == (left_at, ProjectionEndReason.LEFT)
    assert [e.ended_at for e in history.entries if e.organisation_name == "Member 2 Org"] == [None]


async def test_the_leaver_reads_nothing_at_once_and_its_own_data_is_untouched(
    rig: AdminRig,
) -> None:
    a, admin = _a(rig)
    with bind_tenant(a):
        await rig.leave.execute(LeaveNetworkCommand(admin, rig.ids.network))
    with pytest.raises(NotFound):
        await rig.board.execute(rig.viewer(a), rig.ids.network)
    async with rig.reader(a) as uow:
        assert [s.name for s in await uow.services.list_active()] == [rig.world.service_name(a)]


async def test_leaving_closes_the_membership_lapses_the_grants_and_withdraws_the_listing(
    rig: AdminRig,
) -> None:
    a, admin = _a(rig)
    with bind_tenant(a):
        result = await rig.leave.execute(LeaveNetworkCommand(admin, rig.ids.network))
    assert (result.grants_lapsed, result.listings_withdrawn, result.resumed) == (3, 1, False)
    rows = [m for m in await rig.registry.memberships_of(a) if m.network_id == rig.ids.network]
    [row] = rows
    assert (row.status, row.end_reason) == (MembershipStatus.LEFT, MembershipEndReason.LEFT)
    assert {g.status for g in await rig.registry.grants_of(a)} == {GrantStatus.LAPSED}
    assert {x.status for x in await rig.registry.listings_of(rig.ids.network, a)} == {
        ListingStatus.WITHDRAWN
    }
    # the other member keeps everything
    b, _ = _b(rig)
    assert {g.status for g in await rig.registry.grants_of(b)} == {GrantStatus.APPROVED}
    assert _live(rig, await rig.view(), b) == 3


async def test_the_owner_removing_a_member_is_the_same_end_with_its_own_reason(
    rig: AdminRig,
) -> None:
    a, _ = _a(rig)
    membership = await rig.registry.active_membership(rig.ids.network, a)
    assert membership is not None
    with bind_tenant(rig.ids.owner):
        await rig.remove.execute(
            RemoveMemberCommand(rig.people.owner_admin, rig.ids.network, membership.id)
        )
    [row] = [m for m in await rig.registry.memberships_of(a) if m.network_id == rig.ids.network]
    assert (row.status, row.end_reason) == (MembershipStatus.REMOVED, MembershipEndReason.REMOVED)
    assert (
        _live(rig, await rig.view(), a) == 0 and _live(rig, await rig.view(live_only=False), a) == 3
    )
    removed = [e for _, e in []]  # the events are checked below
    assert removed == []
    events = [m for m in await rig.pending_outbox(rig.ids.owner) if m.event_type == "MemberRemoved"]
    assert [m.payload["reason"] for m in events] == ["removed"]


async def test_the_event_of_the_removal_is_handled_by_the_projector_and_ends_nothing_twice(
    rig: AdminRig,
) -> None:
    a, admin = _a(rig)
    with bind_tenant(a):
        await rig.leave.execute(LeaveNetworkCommand(admin, rig.ids.network))
    before = await rig.audit_use_cases(rig.ids.network)
    outcomes = await rig.deliver_events()
    assert "MemberRemoved" in {o[1] for o in outcomes}
    # the use case already ended the sources: the handler finds nothing left to do
    removal = [o for o in outcomes if o[1] == "MemberRemoved"]
    assert all(o[2].value in ("handled", "skipped") for o in removal)
    assert await rig.audit_use_cases(rig.ids.network) == before


async def test_a_member_that_joins_again_is_a_new_membership_with_new_grants_and_live_rows(
    rig: AdminRig,
) -> None:
    a, admin = _a(rig)
    old = await rig.registry.active_membership(rig.ids.network, a)
    assert old is not None
    with bind_tenant(a):
        await rig.leave.execute(LeaveNetworkCommand(admin, rig.ids.network))
    rig.tick(timedelta(hours=2))
    new_id = await rig.join(a, admin)
    assert new_id != old.id
    await rig.share(a, admin, *ALL)
    await rig.list_service(a, admin)
    await rig.deliver_events()
    await rig.apply_pending()
    rows = [m for m in await rig.registry.memberships_of(a) if m.network_id == rig.ids.network]
    assert sorted(m.status.value for m in rows) == ["active", "left"]  # the old row is history
    grants = await rig.registry.grants_of(a)
    assert sorted((g.scope.value, g.version, g.status.value) for g in grants) == sorted(
        [(s.value, 1, "lapsed") for s in ALL] + [(s.value, 2, "approved") for s in ALL]
    )
    live = await rig.view()
    assert _live(rig, live, a) == 3
    assert all(r.ended_at is None for rows_ in live for r in rig.rows_of(a, rows_))
    chain = await rig.audit_use_cases(rig.ids.network)
    assert chain.index("LeaveNetwork") < len(chain) - 1 - chain[::-1].index("InviteMember")


async def test_the_network_chain_and_the_chains_of_the_members_verify_after_all_of_it(
    rig: AdminRig,
) -> None:
    a, admin = _a(rig)
    with bind_tenant(a):
        await rig.leave.execute(LeaveNetworkCommand(admin, rig.ids.network))
    rig.tick(timedelta(hours=1))
    await rig.join(a, admin)
    for scope in (rig.ids.network, rig.ids.owner, a, rig.ids.members[1]):
        assert await rig.verify_chain(scope), scope


async def test_a_second_leave_after_the_first_changes_nothing_and_a_leave_by_a_stranger_is_refused(
    rig: AdminRig,
) -> None:
    a, admin = _a(rig)
    with bind_tenant(a):
        await rig.leave.execute(LeaveNetworkCommand(admin, rig.ids.network))
        before = await rig.audit_use_cases(rig.ids.network)
        again = await rig.leave.execute(LeaveNetworkCommand(admin, rig.ids.network))
    assert again.resumed and await rig.audit_use_cases(rig.ids.network) == before
    with bind_tenant(rig.ids.outsider), pytest.raises(NotFound):
        await rig.leave.execute(LeaveNetworkCommand(rig.people.outsider_admin, rig.ids.network))


async def test_an_invitation_can_be_removed_before_it_is_accepted(rig: AdminRig) -> None:
    c = rig.ids.members[2]
    with bind_tenant(rig.ids.owner):
        invited = await rig.invite.execute(
            InviteMemberCommand(rig.people.owner_admin, rig.ids.network, c)
        )
        await rig.remove.execute(
            RemoveMemberCommand(rig.people.owner_admin, rig.ids.network, invited.membership_id)
        )
    with bind_tenant(c), pytest.raises(NotFound):
        await rig.accept.execute(
            AcceptMembershipCommand(rig.people.admins[2], invited.membership_id, 1)
        )
    assert await rig.registry.active_membership(rig.ids.network, c) is None
