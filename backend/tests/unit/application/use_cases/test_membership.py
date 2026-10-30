"""Network administration, part two: members (TEN-077, DEC-132 items 3 and 6, audit F section 4.5).

The owner's network administrator invites an active organisation; that organisation's own
administrator accepts the agreement version in force; either side ends it (a member leaves, the
owner removes). Ending a membership is where DEC-132 item 6 is kept: the membership closes, its
grants lapse, its listings are withdrawn, its sources in the network scope end with the leave date
and its records are marked, and nothing is deleted. The registry is written first and decides the
race; the rest is repeatable, so a leave that stopped half way is finished by the same command run
again, and nothing is recorded twice.
"""

from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest
from diucs.application.use_cases.membership import (
    AcceptMembership,
    AcceptMembershipCommand,
    InviteMember,
    InviteMemberCommand,
    LeaveNetwork,
    LeaveNetworkCommand,
    RemoveMember,
    RemoveMemberCommand,
)

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.application.tenancy import bind_tenant
from diucs.application.use_cases.network_admin import GovernanceRecorder
from diucs.application.use_cases.network_leave import EndResult
from diucs.domain.codes import Role
from diucs.domain.errors import Conflict, NotAllowed, NotFound
from diucs.domain.model.network import (
    Agreement,
    GrantScope,
    GrantStatus,
    ListingStatus,
    MembershipEndReason,
    MembershipRole,
    MembershipStatus,
    NetworkStatus,
)
from tests.support.network_admin_fakes import (
    Ids,
    MemoryDirectory,
    MemoryRegistry,
    UnitFactories,
    UnitWorld,
    active_tenant,
    person,
)
from tests.support.network_samples import (
    MEMBER_B,
    MEMBER_C,
    NETWORK_ID,
    NOW,
    OTHER_NETWORK_ID,
    OUTSIDER,
    OWNER,
    make_grant,
    make_listing,
    make_member,
    make_network,
    make_owner_membership,
    rid,
)

AT = NOW + timedelta(days=1)


class _Ends:
    """The network scope's half of an end: recorded in the one log, so the order shows."""

    def __init__(self, log: list[str]) -> None:
        self.log = log
        self.calls: list[tuple[str, str, Any]] = []
        self.error: Exception | None = None

    async def end_member(self, network_id: str, member: str, *, at: Any) -> EndResult:
        self.log.append("ends:end_member")
        if self.error is not None:
            raise self.error
        self.calls.append((network_id, member, at))
        return EndResult(3, 4)


class _Rig:
    def __init__(self) -> None:
        self.log: list[str] = []
        self.world = UnitWorld(self.log)
        self.registry = MemoryRegistry(self.log)
        self.registry.seed(
            make_network(),
            members=[make_owner_membership(), make_member(MEMBER_B), make_member(MEMBER_C)],
        )
        self.directory = MemoryDirectory(
            active_tenant(OWNER),
            active_tenant(MEMBER_B),
            active_tenant(MEMBER_C),
            active_tenant(OUTSIDER),
        )
        factories = UnitFactories(self.world)
        self.clock = FixedClock(AT)
        recorder = GovernanceRecorder(
            factories.tenant,  # type: ignore[arg-type]
            factories.network,  # type: ignore[arg-type]
            Ids("ob"),
            self.clock,
        )
        self.ends = _Ends(self.log)
        self.invite = InviteMember(
            self.registry,
            self.directory,
            recorder,
            Ids("mem"),
            self.clock,  # type: ignore[arg-type]
        )
        self.accept = AcceptMembership(self.registry, recorder, self.clock)  # type: ignore[arg-type]
        self.leave = LeaveNetwork(self.registry, self.ends, recorder, self.clock)  # type: ignore[arg-type]
        self.remove = RemoveMember(self.registry, self.ends, recorder, self.clock)  # type: ignore[arg-type]

    def share(self, member: str) -> None:
        for scope in GrantScope:
            grant = make_grant(id=rid(f"grant-{member}-{scope.value}"), tenant=member, scope=scope)
            self.registry.grant_rows[grant.id] = grant
        listing = make_listing(id=rid(f"lst-{member}"), tenant=member)
        self.registry.listing_rows[listing.id] = listing

    def membership_id(self, member: str) -> str:
        return rid(f"mem-{member}")


@pytest.fixture
def rig() -> _Rig:
    return _Rig()


def _owner_admin() -> Any:
    return person(OWNER, Role.NETWORK_ADMIN, "admin")


def _tenant_admin(tenant: str) -> Any:
    return person(tenant, Role.TENANT_ADMIN, "admin")


# inviting


async def test_the_owner_invites_an_active_organisation(rig: _Rig) -> None:
    with bind_tenant(OWNER):
        result = await rig.invite.execute(InviteMemberCommand(_owner_admin(), NETWORK_ID, OUTSIDER))
    row = rig.registry.members[result.membership_id]
    assert (row.member_tenant_id, row.status, row.role) == (
        OUTSIDER,
        MembershipStatus.INVITED,
        MembershipRole.MEMBER,
    )
    assert rig.log.index("registry:create_membership") < rig.log.index("tenant:audit:InviteMember")
    assert [scope for scope, _ in rig.world.audits] == [OWNER, NETWORK_ID]
    assert rig.world.outbox == []  # an invitation is not yet a member: no event


async def test_an_invitation_names_the_membership_and_never_the_invited_organisation(
    rig: _Rig,
) -> None:
    with bind_tenant(OWNER):
        result = await rig.invite.execute(InviteMemberCommand(_owner_admin(), NETWORK_ID, OUTSIDER))
    for _, entry in rig.world.audits:
        assert OUTSIDER not in repr(entry.entity_ids) + repr(entry.snapshot)
        assert result.membership_id in entry.entity_ids


@pytest.mark.parametrize(
    "role", [Role.TENANT_ADMIN, Role.LEAD, Role.OWNER, Role.PLATFORM_OPERATOR, Role.ADVISOR]
)
async def test_only_a_network_administrator_invites(rig: _Rig, role: Role) -> None:
    with bind_tenant(OWNER), pytest.raises(NotAllowed):
        await rig.invite.execute(InviteMemberCommand(person(OWNER, role), NETWORK_ID, OUTSIDER))


async def test_a_network_administrator_of_a_member_is_told_the_network_does_not_exist(
    rig: _Rig,
) -> None:
    with bind_tenant(MEMBER_B), pytest.raises(NotFound):
        await rig.invite.execute(
            InviteMemberCommand(person(MEMBER_B, Role.NETWORK_ADMIN), NETWORK_ID, OUTSIDER)
        )


async def test_an_organisation_that_is_unknown_or_not_active_is_the_same_not_found(
    rig: _Rig,
) -> None:
    from diucs.domain.model.tenant import SuspendMode, SuspendReason, TenantStatus

    rig.directory.tenants["tt-suspended-org"] = replace(
        active_tenant("tt-suspended-org"),
        status=TenantStatus.SUSPENDED,
        suspended_at=NOW,
        suspend_mode=SuspendMode.BLOCKED,
        suspend_reason=SuspendReason.CONTRACT,
    )
    with bind_tenant(OWNER):
        for tenant in ("tt-nobody-here", "tt-suspended-org"):
            with pytest.raises(NotFound) as caught:
                await rig.invite.execute(InviteMemberCommand(_owner_admin(), NETWORK_ID, tenant))
            assert str(caught.value) == "the organisation cannot be invited"
    assert len(rig.registry.members) == 3


async def test_an_organisation_that_is_already_a_member_or_invited_is_a_conflict(
    rig: _Rig,
) -> None:
    with bind_tenant(OWNER):
        with pytest.raises(Conflict):
            await rig.invite.execute(InviteMemberCommand(_owner_admin(), NETWORK_ID, MEMBER_B))
        with pytest.raises(Conflict):
            await rig.invite.execute(InviteMemberCommand(_owner_admin(), NETWORK_ID, OWNER))
        await rig.invite.execute(InviteMemberCommand(_owner_admin(), NETWORK_ID, OUTSIDER))
        with pytest.raises(Conflict):
            await rig.invite.execute(InviteMemberCommand(_owner_admin(), NETWORK_ID, OUTSIDER))


async def test_a_network_that_is_not_active_invites_nobody(rig: _Rig) -> None:
    network, settings = rig.registry.networks[NETWORK_ID]
    rig.registry.networks[NETWORK_ID] = (replace(network, status=NetworkStatus.SUSPENDED), settings)
    with bind_tenant(OWNER), pytest.raises(Conflict):
        await rig.invite.execute(InviteMemberCommand(_owner_admin(), NETWORK_ID, OUTSIDER))


async def test_an_invitation_whose_records_failed_is_taken_back(rig: _Rig) -> None:
    rig.world.fail_commit = "tenant"
    with bind_tenant(OWNER), pytest.raises(ConnectionError):
        await rig.invite.execute(InviteMemberCommand(_owner_admin(), NETWORK_ID, OUTSIDER))
    [row] = [m for m in rig.registry.members.values() if m.member_tenant_id == OUTSIDER]
    assert row.status is MembershipStatus.REMOVED  # compensated: nothing is left waiting
    rig.world.fail_commit = None
    with bind_tenant(OWNER):
        await rig.invite.execute(InviteMemberCommand(_owner_admin(), NETWORK_ID, OUTSIDER))


# accepting


def _invited(rig: _Rig) -> str:
    row = make_member(OUTSIDER, status=MembershipStatus.INVITED, id=rid("mem-out"))
    rig.registry.members[row.id] = row
    return row.id


async def test_the_invited_organisations_administrator_accepts_the_agreement_in_force(
    rig: _Rig,
) -> None:
    mid = _invited(rig)
    with bind_tenant(OUTSIDER):
        await rig.accept.execute(AcceptMembershipCommand(_tenant_admin(OUTSIDER), mid, 1))
    row = rig.registry.members[mid]
    assert row.status is MembershipStatus.ACTIVE and row.accepted_agreement == Agreement(
        "DSA-2026-1", 1
    )
    [(scope, message)] = rig.world.outbox
    assert (scope, message.event_type) == (OUTSIDER, "MemberAdded")  # published by the member
    assert [s for s, _ in rig.world.audits] == [OUTSIDER, NETWORK_ID]


async def test_a_version_the_administrator_did_not_read_is_refused(rig: _Rig) -> None:
    mid = _invited(rig)
    network, settings = rig.registry.networks[NETWORK_ID]
    rig.registry.networks[NETWORK_ID] = (
        replace(network, agreement=Agreement("DSA-2026-2", 2)),
        settings,
    )
    with bind_tenant(OUTSIDER), pytest.raises(Conflict):
        await rig.accept.execute(AcceptMembershipCommand(_tenant_admin(OUTSIDER), mid, 1))
    assert rig.registry.members[mid].status is MembershipStatus.INVITED


async def test_another_organisations_invitation_is_not_found(rig: _Rig) -> None:
    mid = _invited(rig)
    with bind_tenant(MEMBER_C), pytest.raises(NotFound):
        await rig.accept.execute(AcceptMembershipCommand(_tenant_admin(MEMBER_C), mid, 1))


async def test_only_a_tenant_administrator_accepts(rig: _Rig) -> None:
    mid = _invited(rig)
    with bind_tenant(OUTSIDER):
        for role in (Role.NETWORK_ADMIN, Role.LEAD, Role.OWNER):
            with pytest.raises(NotAllowed):
                await rig.accept.execute(AcceptMembershipCommand(person(OUTSIDER, role), mid, 1))


async def test_accepting_twice_changes_and_records_nothing_the_second_time(rig: _Rig) -> None:
    mid = _invited(rig)
    command = AcceptMembershipCommand(_tenant_admin(OUTSIDER), mid, 1)
    with bind_tenant(OUTSIDER):
        await rig.accept.execute(command)
        await rig.accept.execute(command)
    assert len(rig.world.outbox) == 1 and len(rig.world.audits) == 2


async def test_an_invitation_that_was_withdrawn_or_a_membership_that_ended_is_not_found(
    rig: _Rig,
) -> None:
    mid = _invited(rig)
    with bind_tenant(OWNER):
        await rig.remove.execute(RemoveMemberCommand(_owner_admin(), NETWORK_ID, mid))
    with bind_tenant(OUTSIDER), pytest.raises(NotFound):
        await rig.accept.execute(AcceptMembershipCommand(_tenant_admin(OUTSIDER), mid, 1))


async def test_a_suspended_network_cannot_be_joined(rig: _Rig) -> None:
    mid = _invited(rig)
    network, settings = rig.registry.networks[NETWORK_ID]
    rig.registry.networks[NETWORK_ID] = (replace(network, status=NetworkStatus.SUSPENDED), settings)
    with bind_tenant(OUTSIDER), pytest.raises(Conflict):
        await rig.accept.execute(AcceptMembershipCommand(_tenant_admin(OUTSIDER), mid, 1))


# leaving


async def test_a_member_leaves_and_every_effect_follows_in_order(rig: _Rig) -> None:
    rig.share(MEMBER_B)
    with bind_tenant(MEMBER_B):
        result = await rig.leave.execute(LeaveNetworkCommand(_tenant_admin(MEMBER_B), NETWORK_ID))
    row = rig.registry.members[rig.membership_id(MEMBER_B)]
    assert (row.status, row.end_reason, row.left_at) == (
        MembershipStatus.LEFT,
        MembershipEndReason.LEFT,
        AT,
    )
    assert {g.status for g in rig.registry.grant_rows.values()} == {GrantStatus.LAPSED}
    assert {x.status for x in rig.registry.listing_rows.values()} == {ListingStatus.WITHDRAWN}
    assert rig.ends.calls == [(NETWORK_ID, MEMBER_B, AT)]
    assert (result.grants_lapsed, result.listings_withdrawn) == (3, 1)
    order = [
        e
        for e in rig.log
        if e.startswith(
            (
                "registry:save_membership",
                "registry:save_grant",
                "registry:save_listing",
                "ends:",
                "tenant:audit",
                "network:audit",
            )
        )
    ]
    assert order == [
        "registry:save_membership",
        "registry:save_grant",
        "registry:save_grant",
        "registry:save_grant",
        "registry:save_listing",
        "ends:end_member",
        "tenant:audit:LeaveNetwork",
        "network:audit:LeaveNetwork",
    ]


async def test_the_leave_is_published_by_the_member_as_a_removal_with_the_reason_left(
    rig: _Rig,
) -> None:
    with bind_tenant(MEMBER_B):
        await rig.leave.execute(LeaveNetworkCommand(_tenant_admin(MEMBER_B), NETWORK_ID))
    [(scope, message)] = rig.world.outbox
    assert scope == MEMBER_B and message.event_type == "MemberRemoved"
    assert message.payload["reason"] == "left" and message.payload["network_id"] == NETWORK_ID


async def test_another_members_grants_listings_and_network_are_untouched(rig: _Rig) -> None:
    rig.share(MEMBER_B)
    rig.share(MEMBER_C)
    other = make_network(id=OTHER_NETWORK_ID)
    other_row = make_member(MEMBER_B, network=other, id=rid("mem-b-other"))
    rig.registry.networks[other.id] = (other, rig.registry.networks[NETWORK_ID][1])
    rig.registry.members[other_row.id] = other_row
    elsewhere = make_grant(id=rid("grant-elsewhere"), tenant=MEMBER_B, network_id=other.id)
    rig.registry.grant_rows[elsewhere.id] = elsewhere
    with bind_tenant(MEMBER_B):
        await rig.leave.execute(LeaveNetworkCommand(_tenant_admin(MEMBER_B), NETWORK_ID))
    assert rig.registry.grant_rows[elsewhere.id].status is GrantStatus.APPROVED
    assert rig.registry.members[other_row.id].status is MembershipStatus.ACTIVE
    assert all(
        g.status is GrantStatus.APPROVED
        for g in rig.registry.grant_rows.values()
        if g.grantor_tenant_id == MEMBER_C
    )
    assert rig.registry.listing_rows[rid(f"lst-{MEMBER_C}")].status is ListingStatus.ADMITTED


async def test_the_owner_cannot_leave_its_own_network(rig: _Rig) -> None:
    with bind_tenant(OWNER), pytest.raises(NotAllowed):
        await rig.leave.execute(LeaveNetworkCommand(_tenant_admin(OWNER), NETWORK_ID))


async def test_an_organisation_that_never_joined_is_not_found(rig: _Rig) -> None:
    with bind_tenant(OUTSIDER), pytest.raises(NotFound):
        await rig.leave.execute(LeaveNetworkCommand(_tenant_admin(OUTSIDER), NETWORK_ID))


@pytest.mark.parametrize("role", [Role.NETWORK_ADMIN, Role.LEAD, Role.OWNER, Role.REPORTER])
async def test_only_a_tenant_administrator_leaves(rig: _Rig, role: Role) -> None:
    with bind_tenant(MEMBER_B), pytest.raises(NotAllowed):
        await rig.leave.execute(LeaveNetworkCommand(person(MEMBER_B, role), NETWORK_ID))
    assert rig.registry.members[rig.membership_id(MEMBER_B)].status is MembershipStatus.ACTIVE


async def test_a_leave_that_stopped_after_the_registry_is_finished_by_running_it_again(
    rig: _Rig,
) -> None:
    rig.share(MEMBER_B)
    rig.ends.error = ConnectionError("down")
    command = LeaveNetworkCommand(_tenant_admin(MEMBER_B), NETWORK_ID)
    with bind_tenant(MEMBER_B):
        with pytest.raises(ConnectionError):
            await rig.leave.execute(command)
        assert rig.registry.members[rig.membership_id(MEMBER_B)].status is MembershipStatus.LEFT
        assert rig.world.outbox == []
        rig.ends.error = None
        again = await rig.leave.execute(command)
    assert rig.ends.calls == [(NETWORK_ID, MEMBER_B, AT)]
    assert len(rig.world.outbox) == 1 and again.resumed


async def test_a_leave_that_is_repeated_after_it_finished_records_nothing_more(rig: _Rig) -> None:
    command = LeaveNetworkCommand(_tenant_admin(MEMBER_B), NETWORK_ID)
    with bind_tenant(MEMBER_B):
        await rig.leave.execute(command)
        await rig.leave.execute(command)
    assert len(rig.world.outbox) == 1 and len(rig.world.audits) == 2


async def test_the_leave_date_stays_the_first_one_when_it_is_finished_later(rig: _Rig) -> None:
    rig.ends.error = ConnectionError("down")
    command = LeaveNetworkCommand(_tenant_admin(MEMBER_B), NETWORK_ID)
    with bind_tenant(MEMBER_B):
        with pytest.raises(ConnectionError):
            await rig.leave.execute(command)
        rig.clock.set(AT + timedelta(hours=5))
        rig.ends.error = None
        await rig.leave.execute(command)
    assert rig.registry.members[rig.membership_id(MEMBER_B)].left_at == AT
    assert rig.ends.calls[0][2] == AT


async def test_a_grant_ended_by_its_grantor_at_the_same_time_does_not_stop_the_leave(
    rig: _Rig,
) -> None:
    rig.share(MEMBER_B)
    original = rig.registry.save_grant
    first = True

    async def racing(grant: Any, *, expected_status: Any) -> None:
        nonlocal first
        if first:
            first = False
            held = rig.registry.grant_rows[grant.id]
            rig.registry.grant_rows[grant.id] = replace(
                held, status=GrantStatus.ENDED, ended_at=AT, ended_by_account_ref="acct-member-b-01"
            )
        await original(grant, expected_status=expected_status)

    rig.registry.save_grant = racing  # type: ignore[method-assign]
    with bind_tenant(MEMBER_B):
        await rig.leave.execute(LeaveNetworkCommand(_tenant_admin(MEMBER_B), NETWORK_ID))
    assert {g.status for g in rig.registry.grant_rows.values()} <= {
        GrantStatus.LAPSED,
        GrantStatus.ENDED,
    }


# removing


async def test_the_owner_removes_a_member_and_publishes_the_removal(rig: _Rig) -> None:
    rig.share(MEMBER_B)
    with bind_tenant(OWNER):
        await rig.remove.execute(
            RemoveMemberCommand(_owner_admin(), NETWORK_ID, rig.membership_id(MEMBER_B))
        )
    row = rig.registry.members[rig.membership_id(MEMBER_B)]
    assert (row.status, row.end_reason) == (MembershipStatus.REMOVED, MembershipEndReason.REMOVED)
    [(scope, message)] = rig.world.outbox
    assert (scope, message.event_type, message.payload["reason"]) == (
        OWNER,
        "MemberRemoved",
        "removed",
    )
    assert rig.ends.calls == [(NETWORK_ID, MEMBER_B, AT)]


async def test_the_owner_cannot_remove_itself(rig: _Rig) -> None:
    owner_row = rid("mem-owner")
    with bind_tenant(OWNER), pytest.raises(NotAllowed):
        await rig.remove.execute(RemoveMemberCommand(_owner_admin(), NETWORK_ID, owner_row))


async def test_a_membership_of_another_network_is_not_found(rig: _Rig) -> None:
    other = make_network(id=OTHER_NETWORK_ID, owner=MEMBER_C)
    row = make_member(MEMBER_B, network=other, id=rid("mem-elsewhere"))
    rig.registry.networks[other.id] = (other, rig.registry.networks[NETWORK_ID][1])
    rig.registry.members[row.id] = row
    with bind_tenant(OWNER), pytest.raises(NotFound):
        await rig.remove.execute(RemoveMemberCommand(_owner_admin(), NETWORK_ID, row.id))


async def test_a_member_cannot_remove_another_member(rig: _Rig) -> None:
    with bind_tenant(MEMBER_B), pytest.raises(NotAllowed):
        await rig.remove.execute(
            RemoveMemberCommand(_tenant_admin(MEMBER_B), NETWORK_ID, rig.membership_id(MEMBER_C))
        )
    with bind_tenant(MEMBER_B), pytest.raises(NotFound):
        await rig.remove.execute(
            RemoveMemberCommand(
                person(MEMBER_B, Role.NETWORK_ADMIN), NETWORK_ID, rig.membership_id(MEMBER_C)
            )
        )


async def test_an_invitation_that_was_never_accepted_is_removed_without_a_projection_end(
    rig: _Rig,
) -> None:
    mid = _invited(rig)
    with bind_tenant(OWNER):
        await rig.remove.execute(RemoveMemberCommand(_owner_admin(), NETWORK_ID, mid))
    assert rig.registry.members[mid].status is MembershipStatus.REMOVED
