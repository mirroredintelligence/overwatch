"""Network administration on a real Neo4j: network, members, agreement and listings (TEN-077,
DEC-132, DEC-136 items 3 and 10, DEC-541, the known gap of DEC-543 item 7).

The rig drives the product's own use cases (`tests/support/network_admin_rig.py`): the operator
creates the network, the owner's administrator invites, a member's administrator accepts, a lead
lists a service and the owner admits it. The things only a real graph can say are looked at: the
network has its own audit chain from the moment it exists, every action is in the chain of the
tenant that did it and in the network's, the registry holds the rows, nothing of a member's data
is in the network scope, and the owner reads no member's tenant scope.
"""

import os
from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
import pytest_asyncio
from neo4j import AsyncDriver

from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.application.tenancy import bind_tenant
from diucs.application.use_cases.listing_admission import DecideListingCommand, ListingDecision
from diucs.application.use_cases.membership import LeaveNetworkCommand
from diucs.application.use_cases.network_admin import CreateNetworkCommand, RecordAgreementCommand
from diucs.domain.errors import Conflict, NotFound
from diucs.domain.model.network import (
    GrantScope,
    ListingReason,
    ListingStatus,
    MembershipRole,
    MembershipStatus,
    NetworkStatus,
)
from tests.support.network_admin_rig import AdminRig
from tests.support.network_world import NETWORK_INVARIANTS, world_ids
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
    yield built
    await built.cleanup()


async def test_a_network_is_created_with_its_own_audit_chain_and_the_owner_as_a_member(
    rig: AdminRig,
) -> None:
    await rig.make_network()
    registered = await rig.registry.get_network(rig.ids.network)
    assert registered is not None
    assert registered.network.status is NetworkStatus.ACTIVE
    assert registered.network.owner_tenant_id == rig.ids.owner
    [owner] = await rig.registry.memberships(rig.ids.network)
    assert (owner.member_tenant_id, owner.role, owner.status) == (
        rig.ids.owner,
        MembershipRole.OWNER,
        MembershipStatus.ACTIVE,
    )
    # the chain exists and already holds the creation, in the network's scope and the owner's
    assert await rig.audit_use_cases(rig.ids.network) == ["CreateNetwork"]
    assert (await rig.audit_use_cases(rig.ids.owner))[-1:] == ["CreateNetwork"]
    assert [m.event_type for m in await rig.pending_outbox(rig.ids.owner)] == ["NetworkCreated"]


async def test_creating_it_again_is_a_repeat_and_a_different_network_under_the_id_is_refused(
    rig: AdminRig,
) -> None:
    await rig.make_network()
    await rig.make_network()
    assert await rig.audit_use_cases(rig.ids.network) == ["CreateNetwork"]
    assert len(await rig.registry.memberships(rig.ids.network)) == 1
    with bind_tenant(rig.ids.owner), pytest.raises(Conflict):
        await rig.create_network.execute(
            CreateNetworkCommand(
                actor=rig.people.operator,
                network_id=rig.ids.network,
                name="A different network",
                agreement_reference="DSA-2026-1",
                agreement_version=1,
                system_name="Sample capacity board",
                pathway_name="Sample urgent pathway",
            )
        )


async def test_a_member_joins_and_every_step_is_in_both_chains(rig: AdminRig) -> None:
    await rig.make_network()
    member = rig.ids.members[0]
    await rig.join(member, rig.people.admins[0])
    assert await rig.audit_use_cases(rig.ids.network) == [
        "CreateNetwork",
        "InviteMember",
        "AcceptMembership",
    ]
    assert (await rig.audit_use_cases(member))[-1:] == ["AcceptMembership"]
    assert (await rig.audit_use_cases(rig.ids.owner))[-2:] == ["CreateNetwork", "InviteMember"]
    active = await rig.registry.active_membership(rig.ids.network, member)
    assert active is not None and active.accepted_agreement is not None


async def test_an_unaccepted_invitation_is_not_a_member_and_sees_no_network(rig: AdminRig) -> None:
    from diucs.application.use_cases.membership import InviteMemberCommand

    await rig.make_network()
    member = rig.ids.members[1]
    with bind_tenant(rig.ids.owner):
        await rig.invite.execute(
            InviteMemberCommand(rig.people.owner_admin, rig.ids.network, member)
        )
    assert await rig.registry.active_membership(rig.ids.network, member) is None
    with bind_tenant(member):
        [view] = await rig.admin_query.networks(rig.people.admins[1])
    assert view.membership_status is MembershipStatus.INVITED
    with pytest.raises(NotFound):
        await rig.access.require_member(rig.viewer(member), rig.ids.network)


async def test_a_new_agreement_version_marks_every_member_behind_until_it_accepts_nothing_more(
    rig: AdminRig,
) -> None:
    await rig.make_network()
    await rig.join(rig.ids.members[0], rig.people.admins[0])
    with bind_tenant(rig.ids.owner):
        await rig.record_agreement.execute(
            RecordAgreementCommand(rig.people.owner_admin, rig.ids.network, "DSA-2026-2", 2)
        )
        rows = await rig.admin_query.members(rig.people.owner_admin, rig.ids.network)
    assert [r.agreement_behind for r in rows] == [True, True]
    with bind_tenant(rig.ids.members[0]):
        [view] = await rig.admin_query.networks(rig.people.admins[0])
    assert view.agreement_behind and view.agreement_version == 2


async def test_a_listing_is_asked_by_the_member_and_admitted_by_the_owner(rig: AdminRig) -> None:
    await rig.make_network()
    member = rig.ids.members[0]
    await rig.join(member, rig.people.admins[0])
    lid = await rig.list_service(member, rig.people.admins[0])
    listing = await rig.registry.get_listing(lid)
    assert listing is not None and listing.status is ListingStatus.ADMITTED
    assert listing.source_tenant_id == member
    assert "RequestListing" in await rig.audit_use_cases(rig.ids.network)
    assert "AdmitListing" in await rig.audit_use_cases(rig.ids.network)
    with bind_tenant(rig.ids.owner):
        [row] = await rig.listing_query.for_network(rig.people.owner_admin, rig.ids.network)
    assert row.organisation_name == "Member 1 Org" and member not in repr(row)


async def test_a_suspended_listing_stops_projecting_and_a_reinstated_one_resumes(
    rig: AdminRig,
) -> None:
    await rig.make_network()
    member = rig.ids.members[0]
    admin = rig.people.admins[0]
    await rig.join(member, admin)
    await rig.share(member, admin, *GrantScope)
    lid = await rig.list_service(member, admin)
    await rig.deliver_events()
    assert all(r.outcome.value == "applied" for r in await rig.project(member))
    with bind_tenant(rig.ids.owner):
        await rig.decide_listing.execute(
            DecideListingCommand(
                rig.people.owner_admin,
                rig.ids.network,
                lid,
                ListingDecision.SUSPEND,
                ListingReason.DATA_QUALITY,
            )
        )
    rig.tick(timedelta(minutes=1))
    assert await rig.project(member) == []  # the producer's gate: nothing new is built
    with bind_tenant(rig.ids.owner):
        await rig.decide_listing.execute(
            DecideListingCommand(
                rig.people.owner_admin, rig.ids.network, lid, ListingDecision.REINSTATE
            )
        )
    assert len(await rig.project(member)) == 3


async def test_the_owner_reads_the_projection_state_of_a_member_and_never_a_row(
    rig: AdminRig,
) -> None:
    await rig.make_network()
    member = rig.ids.members[0]
    admin = rig.people.admins[0]
    await rig.join(member, admin)
    await rig.share(member, admin, *GrantScope)
    await rig.list_service(member, admin)
    await rig.deliver_events()
    await rig.project(member)
    with bind_tenant(rig.ids.owner):
        [status] = await rig.admin_query.projection_status(rig.people.owner_admin, rig.ids.network)
    assert status.organisation_name == "Member 1 Org"
    assert {k.kind for k in status.kinds} == set(GrantScope)
    assert all(k.status.value == "active" for k in status.kinds)
    for poison in rig.world.poison.get(member, ()):
        assert poison not in repr(status)


async def test_a_member_that_leaves_keeps_its_history_and_the_leave_is_in_both_chains(
    rig: AdminRig,
) -> None:
    await rig.make_network()
    member = rig.ids.members[0]
    admin = rig.people.admins[0]
    await rig.join(member, admin)
    await rig.share(member, admin, *GrantScope)
    await rig.list_service(member, admin)
    await rig.deliver_events()
    await rig.project(member)
    rig.tick(timedelta(hours=1))
    with bind_tenant(member):
        result = await rig.leave.execute(LeaveNetworkCommand(admin, rig.ids.network))
    assert (result.grants_lapsed, result.listings_withdrawn, result.sources_ended) == (3, 1, 3)
    live, every = await rig.view(), await rig.view(live_only=False)
    assert all(rig.rows_of(member, rows) == [] for rows in live)
    assert all(len(rig.rows_of(member, rows)) == 1 for rows in every)
    assert "LeaveNetwork" in await rig.audit_use_cases(rig.ids.network)
    assert "LeaveNetwork" in await rig.audit_use_cases(member)
    # the member's own data is untouched
    async with rig.reader(member) as uow:
        assert [s.name for s in await uow.services.list_active()] == [
            rig.world.service_name(member)
        ]


async def test_no_invariant_of_the_network_scope_is_broken_by_any_of_it(rig: AdminRig) -> None:
    await rig.make_network()
    member = rig.ids.members[2]
    admin = rig.people.admins[2]
    await rig.join(member, admin)
    await rig.share(member, admin, *GrantScope)
    await rig.list_service(member, admin)
    await rig.deliver_events()
    await rig.project(member)
    found = await rig.world.invariants()
    assert set(found) == set(NETWORK_INVARIANTS)
    assert all(rows == [] for rows in found.values()), found
