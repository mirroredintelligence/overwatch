"""Grants and the cross-scope saga on a real Neo4j (TEN-078, DEC-132 items 3 and 6, DEC-134 item 6).

The rig drives the product's own use cases over the real registry, units of work and audit chains
(`tests/support/network_admin_rig.py`). What only a real graph can say is looked at: the registry
holds the grant in the state each step left it, each action is in the chain of the tenant that did
it and in the network's, the events wait on the acting tenant's outbox for the relay, the registry
decides a race, a repeated command changes and records nothing twice, a revision replaces its
predecessor with no gap, and nothing a grant does reaches a member's scope except through the
projector.
"""

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
import pytest_asyncio
from neo4j import AsyncDriver

from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.application.tenancy import bind_tenant
from diucs.application.use_cases.grants import (
    ApproveGrantCommand,
    DeclineGrantCommand,
    EndGrantCommand,
    ProposeGrantCommand,
    ReviseGrantCommand,
)
from diucs.domain.errors import Conflict, InvalidTransition, NotFound
from diucs.domain.model.network import GrantScope, GrantStatus
from diucs.domain.rules.grant import is_effective
from tests.support.network_admin_rig import AdminRig
from tests.support.network_world import world_ids
from tests.support.tenancy import RunIdentity

pytestmark = pytest.mark.asyncio(loop_scope="session")


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
    for member, admin in zip(built.ids.members, built.people.admins, strict=True):
        await built.join(member, admin)
    yield built
    await built.cleanup()


async def _propose(rig: AdminRig, scope: GrantScope = GrantScope.CAPACITY, **kw: object) -> str:
    member, admin = rig.ids.members[0], rig.people.admins[0]
    with bind_tenant(member):
        return await rig.propose.execute(
            ProposeGrantCommand(admin, rig.ids.network, scope, **kw)  # type: ignore[arg-type]
        )


async def _approve(rig: AdminRig, gid: str, *, owner: bool) -> bool:
    if owner:
        with bind_tenant(rig.ids.owner):
            result = await rig.approve.execute(ApproveGrantCommand(rig.people.owner_admin, gid))
    else:
        with bind_tenant(rig.ids.members[0]):
            result = await rig.approve.execute(ApproveGrantCommand(rig.people.admins[0], gid))
    return result.effective


async def test_the_two_approvals_make_the_grant_effective_and_each_step_is_recorded_twice(
    rig: AdminRig,
) -> None:
    member = rig.ids.members[0]
    gid = await _propose(rig)
    grant = await rig.registry.get_grant(gid)
    assert grant is not None and grant.status is GrantStatus.PROPOSED and grant.version == 1
    assert await _approve(rig, gid, owner=False) is False
    assert await _approve(rig, gid, owner=True) is True
    grant = await rig.registry.get_grant(gid)
    assert grant is not None and is_effective(grant, rig.clock.now())
    network_chain = await rig.audit_use_cases(rig.ids.network)
    assert network_chain[-3:] == ["ProposeGrant", "ApproveGrant", "ApproveGrant"]
    assert (await rig.audit_use_cases(member))[-2:] == ["ProposeGrant", "ApproveGrant"]
    assert (await rig.audit_use_cases(rig.ids.owner))[-1:] == ["ApproveGrant"]
    # the relay publishes in the order of the rows; the clock here does not move, so the order of
    # events of one instant is not asserted, only what each organisation published
    mine = [m.event_type for m in await rig.pending_outbox(member)]
    assert mine.count("GrantProposed") == 1 and mine.count("GrantApproved") == 1
    theirs = [m.event_type for m in await rig.pending_outbox(rig.ids.owner)]
    assert theirs.count("GrantApproved") == 1 and theirs.count("GrantEffective") == 1


async def test_one_person_gives_only_one_of_the_two_approvals(rig: AdminRig) -> None:
    """The member is its own network's owner for this one test: a grant of the owner's own."""
    from diucs.domain.codes import Role
    from tests.support.network_admin_fakes import person

    owner = rig.ids.owner
    one = person(owner, Role.TENANT_ADMIN, "same")
    same = person(owner, Role.NETWORK_ADMIN, "same")
    with bind_tenant(owner):
        gid = await rig.propose.execute(
            ProposeGrantCommand(one, rig.ids.network, GrantScope.CAPACITY)
        )
        await rig.approve.execute(ApproveGrantCommand(one, gid))
        with pytest.raises(Conflict):
            await rig.approve.execute(ApproveGrantCommand(same, gid))
        done = await rig.approve.execute(
            ApproveGrantCommand(person(owner, Role.NETWORK_ADMIN, "second"), gid)
        )
    assert done.effective


async def test_approving_twice_and_ending_twice_change_and_record_nothing_the_second_time(
    rig: AdminRig,
) -> None:
    member = rig.ids.members[0]
    gid = await _propose(rig)
    await _approve(rig, gid, owner=False)
    await _approve(rig, gid, owner=False)
    await _approve(rig, gid, owner=True)
    with bind_tenant(member):
        await rig.end_grant.execute(EndGrantCommand(rig.people.admins[0], gid))
        before = await rig.audit_use_cases(rig.ids.network)
        rig.tick(timedelta(minutes=5))
        await rig.end_grant.execute(EndGrantCommand(rig.people.admins[0], gid))
    assert await rig.audit_use_cases(rig.ids.network) == before
    grant = await rig.registry.get_grant(gid)
    assert grant is not None and grant.status is GrantStatus.ENDED
    assert grant.ended_at == rig.clock.now() - timedelta(minutes=5)


async def test_the_grantor_alone_ends_a_grant_and_the_owner_and_others_cannot(
    rig: AdminRig,
) -> None:
    from diucs.domain.errors import NotAllowed

    gid = await _propose(rig)
    await _approve(rig, gid, owner=False)
    await _approve(rig, gid, owner=True)
    with bind_tenant(rig.ids.owner), pytest.raises(NotAllowed):
        await rig.end_grant.execute(EndGrantCommand(rig.people.owner_admin, gid))
    other = rig.ids.members[1]
    with bind_tenant(other), pytest.raises(NotFound):
        await rig.end_grant.execute(EndGrantCommand(rig.people.admins[1], gid))
    grant = await rig.registry.get_grant(gid)
    assert grant is not None and grant.status is GrantStatus.APPROVED


async def test_a_declined_grant_is_ended_for_good_and_cannot_be_approved(rig: AdminRig) -> None:
    gid = await _propose(rig)
    with bind_tenant(rig.ids.owner):
        await rig.decline.execute(DeclineGrantCommand(rig.people.owner_admin, gid))
    with pytest.raises(InvalidTransition):
        await _approve(rig, gid, owner=False)
    await _propose(rig)  # a new proposal of the scope is allowed, as the next version
    versions = sorted(
        g.version
        for g in await rig.registry.grants_of(rig.ids.members[0])
        if g.scope is GrantScope.CAPACITY
    )
    assert versions == [1, 2]


async def test_the_grantor_and_the_owner_approving_at_once_both_land(rig: AdminRig) -> None:
    gid = await _propose(rig)
    results = await asyncio.gather(
        _approve(rig, gid, owner=False), _approve(rig, gid, owner=True), return_exceptions=True
    )
    assert not [r for r in results if isinstance(r, Exception)], results
    grant = await rig.registry.get_grant(gid)
    assert grant is not None and grant.status is GrantStatus.APPROVED
    assert grant.grantor_approval is not None and grant.owner_approval is not None


async def test_an_approval_racing_an_end_leaves_one_consistent_state(rig: AdminRig) -> None:
    gid = await _propose(rig)
    await _approve(rig, gid, owner=False)
    member = rig.ids.members[0]

    async def end() -> None:
        with bind_tenant(member):
            await rig.end_grant.execute(EndGrantCommand(rig.people.admins[0], gid))

    results = await asyncio.gather(_approve(rig, gid, owner=True), end(), return_exceptions=True)
    grant = await rig.registry.get_grant(gid)
    assert grant is not None
    # either the end won (the approval is refused) or the approval won and the end followed it
    assert grant.status is GrantStatus.ENDED
    assert all(isinstance(r, (bool, type(None), InvalidTransition, Conflict)) for r in results), (
        results
    )


async def test_a_revision_replaces_its_predecessor_when_it_starts_with_no_gap(
    rig: AdminRig,
) -> None:
    member = rig.ids.members[0]
    gid = await _propose(rig)
    await _approve(rig, gid, owner=False)
    await _approve(rig, gid, owner=True)
    start = rig.clock.now() + timedelta(days=2)
    with bind_tenant(member):
        new_id = await rig.revise.execute(
            ReviseGrantCommand(rig.people.admins[0], gid, effective_from=start)
        )
    for owner in (False, True):
        await _approve(rig, new_id, owner=owner)
    old = await rig.registry.get_grant(gid)
    new = await rig.registry.get_grant(new_id)
    assert old is not None and new is not None
    assert old.status is GrantStatus.APPROVED and new.status is GrantStatus.APPROVED
    now = rig.clock.now()
    assert is_effective(old, now) and not is_effective(new, now)
    rig.tick(timedelta(days=2))
    with bind_tenant(member):
        assert await rig.supersede.execute() == 1
    old = await rig.registry.get_grant(gid)
    assert old is not None and old.status is GrantStatus.SUPERSEDED and old.effective_to == start
    now = rig.clock.now()
    new = await rig.registry.get_grant(new_id)
    assert new is not None and is_effective(new, now) and not is_effective(old, now)
    # at the instant the successor starts exactly one of them is effective
    assert is_effective(new, start) and not is_effective(old, start)


async def test_a_member_sees_only_its_own_grants_and_the_owner_sees_every_one(
    rig: AdminRig,
) -> None:
    await _propose(rig)
    other = rig.ids.members[1]
    with bind_tenant(other):
        await rig.propose.execute(
            ProposeGrantCommand(rig.people.admins[1], rig.ids.network, GrantScope.DIRECTORY)
        )
        mine = await rig.grant_query.for_tenant(rig.people.admins[1])
    assert [g.scope for g in mine] == [GrantScope.DIRECTORY]
    with bind_tenant(rig.ids.owner):
        every = await rig.grant_query.for_network(rig.people.owner_admin, rig.ids.network)
    assert {g.scope for g in every} == {GrantScope.DIRECTORY, GrantScope.CAPACITY}
    assert all(rig.ids.members[0] not in repr(g) for g in every)


async def test_nothing_a_grant_does_writes_into_a_members_scope_but_its_own_audit_and_outbox(
    rig: AdminRig,
) -> None:
    member = rig.ids.members[0]
    before = {
        label: await rig.count(member, label)
        for label in ("HealthcareService", "Communication", "ScheduledWork")
    }
    gid = await _propose(rig)
    await _approve(rig, gid, owner=False)
    await _approve(rig, gid, owner=True)
    after = {label: await rig.count(member, label) for label in before}
    assert after == before
