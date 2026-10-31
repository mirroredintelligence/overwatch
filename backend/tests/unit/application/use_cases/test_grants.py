"""Network administration, part four: grants and the cross-scope saga (TEN-078, DEC-132 items 3 and
6, DEC-134 item 6, audit F section 4.6).

A grant is the only way data is shared. The grantor's administrator proposes one scope for the
network's one purpose under the agreement version in force; the grantor's administrator and the
network owner's administrator each approve it (two people: the same account cannot give both); it
is effective from its start, computed and never stored; the grantor ends it alone, and ending it
stops future sharing only (its source and rows end in the network scope with the date, nothing is
deleted); a revision is a new version that replaces it with no gap and no overlap. The registry is
written first and decides a race; the records and the network scope follow, repeatably, so a command
that stopped half way is finished by running it again.
"""

from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.application.tenancy import bind_tenant
from diucs.application.use_cases.grants import (
    ApproveGrant,
    ApproveGrantCommand,
    DeclineGrant,
    DeclineGrantCommand,
    EndGrant,
    EndGrantCommand,
    ProposeGrant,
    ProposeGrantCommand,
    QueryGrants,
    ReviseGrant,
    ReviseGrantCommand,
    SupersedeDueGrants,
)
from diucs.application.use_cases.network_admin import GovernanceRecorder
from diucs.application.use_cases.network_leave import EndResult
from diucs.domain.codes import Role
from diucs.domain.errors import Conflict, InvalidTransition, NotAllowed, NotFound, ValidationFailed
from diucs.domain.model.network import (
    GrantEndReason,
    GrantPurpose,
    GrantScope,
    GrantStatus,
    NetworkStatus,
)
from diucs.domain.rules.grant import is_effective
from diucs.domain.rules.projection import PROJECTION_ALLOWLIST_VERSION
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
    OUTSIDER,
    OWNER,
    make_grant,
    make_member,
    make_network,
    make_owner_membership,
    rid,
)

AT = NOW + timedelta(days=1)
GRANT_ID = rid("grant-live")


class _Ends:
    def __init__(self, log: list[str]) -> None:
        self.log = log
        self.calls: list[tuple[Any, ...]] = []
        self.error: Exception | None = None

    async def end_grant(
        self, network: str, member: str, scope: Any, *, reason: Any, at: Any
    ) -> Any:
        self.log.append("ends:end_grant")
        if self.error is not None:
            raise self.error
        self.calls.append((network, member, scope, reason, at))
        return EndResult(1, 2)


class _Rig:
    def __init__(self) -> None:
        self.log: list[str] = []
        self.world = UnitWorld(self.log)
        self.registry = MemoryRegistry(self.log)
        self.registry.seed(
            make_network(),
            members=[make_owner_membership(), make_member(MEMBER_B), make_member(MEMBER_C)],
        )
        self.clock = FixedClock(AT)
        factories = UnitFactories(self.world)
        self.ids = Ids("grant")
        self.recorder = GovernanceRecorder(
            factories.tenant,  # type: ignore[arg-type]
            factories.network,  # type: ignore[arg-type]
            Ids("ob"),
            self.clock,
        )
        self.ends = _Ends(self.log)
        reg: Any = self.registry
        self.propose = ProposeGrant(reg, self.recorder, self.ids, self.clock)
        self.approve = ApproveGrant(reg, self.recorder, self.clock)
        self.decline = DeclineGrant(reg, self.recorder, self.clock)
        self.end = EndGrant(reg, self.ends, self.recorder, self.clock)  # type: ignore[arg-type]
        self.revise = ReviseGrant(reg, self.recorder, Ids("rev"), self.clock)
        self.supersede = SupersedeDueGrants(reg, self.recorder, self.clock)
        self.query = QueryGrants(
            reg,
            MemoryDirectory(active_tenant(OWNER), active_tenant(MEMBER_B), active_tenant(MEMBER_C)),  # type: ignore[arg-type]
            self.clock,
        )

    def grant(self, **over: Any) -> Any:
        grant = make_grant(id=over.pop("id", GRANT_ID), **over)
        self.registry.grant_rows[grant.id] = grant
        return grant

    def events(self) -> list[tuple[str, str]]:
        return [(scope, m.event_type) for scope, m in self.world.outbox]


@pytest.fixture
def rig() -> _Rig:
    return _Rig()


def _tenant_admin(tenant: str = MEMBER_B, who: str = "admin") -> Any:
    return person(tenant, Role.TENANT_ADMIN, who)


def _network_admin(who: str = "admin") -> Any:
    return person(OWNER, Role.NETWORK_ADMIN, who)


async def _propose(rig: _Rig, scope: GrantScope = GrantScope.CAPACITY, **over: Any) -> str:
    with bind_tenant(MEMBER_B):
        return await rig.propose.execute(
            ProposeGrantCommand(_tenant_admin(), NETWORK_ID, scope, **over)
        )


# proposing


async def test_a_member_proposes_one_scope_under_the_agreement_in_force(rig: _Rig) -> None:
    gid = await _propose(rig)
    grant = rig.registry.grant_rows[gid]
    assert (grant.status, grant.version, grant.scope, grant.purpose) == (
        GrantStatus.PROPOSED,
        1,
        GrantScope.CAPACITY,
        GrantPurpose.NETWORK_CAPACITY_VIEW,
    )
    assert (grant.agreement.version, grant.allowlist_version) == (1, PROJECTION_ALLOWLIST_VERSION)
    assert (grant.grantor_tenant_id, grant.effective_from, grant.effective_to) == (
        MEMBER_B,
        AT,
        None,
    )
    assert rig.events() == [(MEMBER_B, "GrantProposed")]
    assert [s for s, _ in rig.world.audits] == [MEMBER_B, NETWORK_ID]


async def test_a_start_and_an_end_may_be_given_and_the_start_may_not_be_in_the_past(
    rig: _Rig,
) -> None:
    start = AT + timedelta(days=2)
    gid = await _propose(rig, effective_from=start, effective_to=start + timedelta(days=30))
    assert rig.registry.grant_rows[gid].effective_to == start + timedelta(days=30)
    with pytest.raises(ValidationFailed):
        await _propose(rig, GrantScope.DIRECTORY, effective_from=AT - timedelta(minutes=1))
    with pytest.raises(ValidationFailed):
        await _propose(
            rig, GrantScope.CRITERIA, effective_from=start, effective_to=start - timedelta(days=1)
        )


@pytest.mark.parametrize("role", [Role.NETWORK_ADMIN, Role.LEAD, Role.OWNER, Role.ADVISOR])
async def test_only_a_tenant_administrator_proposes(rig: _Rig, role: Role) -> None:
    with bind_tenant(MEMBER_B), pytest.raises(NotAllowed):
        await rig.propose.execute(
            ProposeGrantCommand(person(MEMBER_B, role), NETWORK_ID, GrantScope.CAPACITY)
        )


async def test_an_organisation_that_is_not_a_member_proposes_nothing(rig: _Rig) -> None:
    with bind_tenant(OUTSIDER), pytest.raises(NotFound):
        await rig.propose.execute(
            ProposeGrantCommand(_tenant_admin(OUTSIDER), NETWORK_ID, GrantScope.CAPACITY)
        )
    assert rig.registry.grant_rows == {}


async def test_a_scope_with_an_open_grant_must_be_revised_not_proposed_again(rig: _Rig) -> None:
    await _propose(rig)
    with pytest.raises(Conflict):
        await _propose(rig)
    await _propose(rig, GrantScope.DIRECTORY)


async def test_a_new_grant_after_an_ended_one_takes_the_next_version(rig: _Rig) -> None:
    first = make_grant(id=rid("grant-old"), tenant=MEMBER_B)
    ended = replace(
        first, status=GrantStatus.ENDED, ended_at=NOW, ended_by_account_ref="acct-member-b-01"
    )
    rig.registry.grant_rows[ended.id] = ended
    gid = await _propose(rig)
    assert rig.registry.grant_rows[gid].version == 2


async def test_a_network_that_is_not_active_takes_no_proposal(rig: _Rig) -> None:
    network, settings = rig.registry.networks[NETWORK_ID]
    rig.registry.networks[NETWORK_ID] = (replace(network, status=NetworkStatus.SUSPENDED), settings)
    with pytest.raises(Conflict):
        await _propose(rig)


async def test_a_proposal_whose_records_failed_is_declined_again(rig: _Rig) -> None:
    rig.world.fail_commit = "tenant"
    with pytest.raises(ConnectionError):
        await _propose(rig)
    [grant] = rig.registry.grant_rows.values()
    assert grant.status is GrantStatus.DECLINED
    rig.world.fail_commit = None
    await _propose(rig)


# approving


def _proposed(rig: _Rig) -> Any:
    grant = make_grant(id=GRANT_ID, tenant=MEMBER_B, approved=False)
    rig.registry.grant_rows[grant.id] = grant
    return grant


async def test_the_two_approvals_make_a_grant_effective_in_either_order(rig: _Rig) -> None:
    _proposed(rig)
    with bind_tenant(MEMBER_B):
        first = await rig.approve.execute(ApproveGrantCommand(_tenant_admin(), GRANT_ID))
    assert first.effective is False
    assert rig.registry.grant_rows[GRANT_ID].status is GrantStatus.GRANTOR_APPROVED
    assert rig.events() == [(MEMBER_B, "GrantApproved")]
    with bind_tenant(OWNER):
        second = await rig.approve.execute(ApproveGrantCommand(_network_admin(), GRANT_ID))
    grant = rig.registry.grant_rows[GRANT_ID]
    assert second.effective is True and grant.status is GrantStatus.APPROVED
    assert is_effective(grant, AT)
    assert rig.events() == [
        (MEMBER_B, "GrantApproved"),
        (OWNER, "GrantApproved"),
        (OWNER, "GrantEffective"),
    ]


async def test_the_owner_may_approve_first(rig: _Rig) -> None:
    _proposed(rig)
    with bind_tenant(OWNER):
        await rig.approve.execute(ApproveGrantCommand(_network_admin(), GRANT_ID))
    with bind_tenant(MEMBER_B):
        done = await rig.approve.execute(ApproveGrantCommand(_tenant_admin(), GRANT_ID))
    assert done.effective
    assert rig.events()[-1] == (MEMBER_B, "GrantEffective")


async def test_the_effective_event_names_when_it_takes_effect_and_the_grant_and_no_more(
    rig: _Rig,
) -> None:
    start = AT + timedelta(days=3)
    rig.registry.grant_rows[GRANT_ID] = make_grant(
        id=GRANT_ID, tenant=MEMBER_B, approved=False, effective_from=start
    )
    with bind_tenant(MEMBER_B):
        await rig.approve.execute(ApproveGrantCommand(_tenant_admin(), GRANT_ID))
    with bind_tenant(OWNER):
        await rig.approve.execute(ApproveGrantCommand(_network_admin(), GRANT_ID))
    [effective] = [m for _, m in rig.world.outbox if m.event_type == "GrantEffective"]
    assert effective.payload["effective_from"] == start.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert set(effective.payload) == {
        "grant_id",
        "network_id",
        "grantor_tenant_id",
        "scope",
        "version",
        "effective_from",
        "at",
    }
    # approved but not yet started: not effective now
    assert not is_effective(rig.registry.grant_rows[GRANT_ID], AT)


async def test_one_person_cannot_give_both_approvals_when_grantor_and_owner_are_one_tenant(
    rig: _Rig,
) -> None:
    grant = make_grant(id=GRANT_ID, tenant=OWNER, approved=False)
    rig.registry.grant_rows[grant.id] = grant
    me = person(OWNER, Role.TENANT_ADMIN, "same")
    also = person(OWNER, Role.NETWORK_ADMIN, "same")
    with bind_tenant(OWNER):
        await rig.approve.execute(ApproveGrantCommand(me, GRANT_ID))
        with pytest.raises(Conflict):
            await rig.approve.execute(ApproveGrantCommand(also, GRANT_ID))
        done = await rig.approve.execute(
            ApproveGrantCommand(person(OWNER, Role.NETWORK_ADMIN, "second"), GRANT_ID)
        )
    assert done.effective


async def test_approving_twice_by_the_same_person_changes_and_records_nothing_more(
    rig: _Rig,
) -> None:
    _proposed(rig)
    command = ApproveGrantCommand(_tenant_admin(), GRANT_ID)
    with bind_tenant(MEMBER_B):
        await rig.approve.execute(command)
        await rig.approve.execute(command)
    assert len(rig.world.outbox) == 1 and len(rig.world.audits) == 2


async def test_another_grantors_grant_and_an_outsiders_approval_are_not_found(rig: _Rig) -> None:
    _proposed(rig)
    with bind_tenant(MEMBER_C), pytest.raises(NotFound):
        await rig.approve.execute(ApproveGrantCommand(_tenant_admin(MEMBER_C), GRANT_ID))
    with bind_tenant(MEMBER_B), pytest.raises(NotFound):
        await rig.approve.execute(
            ApproveGrantCommand(person(MEMBER_B, Role.NETWORK_ADMIN), GRANT_ID)
        )
    with bind_tenant(MEMBER_B), pytest.raises(NotFound):
        await rig.approve.execute(ApproveGrantCommand(_tenant_admin(), "grant-nope"))
    assert rig.registry.grant_rows[GRANT_ID].status is GrantStatus.PROPOSED


@pytest.mark.parametrize("role", [Role.LEAD, Role.OWNER, Role.PLATFORM_OPERATOR])
async def test_only_the_two_administrators_approve(rig: _Rig, role: Role) -> None:
    _proposed(rig)
    with bind_tenant(MEMBER_B), pytest.raises(NotAllowed):
        await rig.approve.execute(ApproveGrantCommand(person(MEMBER_B, role), GRANT_ID))


async def test_an_ended_grant_cannot_be_approved(rig: _Rig) -> None:
    grant = _proposed(rig)
    rig.registry.grant_rows[GRANT_ID] = replace(
        grant, status=GrantStatus.ENDED, ended_at=NOW, ended_by_account_ref="acct-member-b-01"
    )
    with bind_tenant(MEMBER_B), pytest.raises(InvalidTransition):
        await rig.approve.execute(ApproveGrantCommand(_tenant_admin(), GRANT_ID))


async def test_an_approval_when_the_network_is_not_active_is_refused(rig: _Rig) -> None:
    _proposed(rig)
    network, settings = rig.registry.networks[NETWORK_ID]
    rig.registry.networks[NETWORK_ID] = (replace(network, status=NetworkStatus.SUSPENDED), settings)
    with bind_tenant(MEMBER_B), pytest.raises(Conflict):
        await rig.approve.execute(ApproveGrantCommand(_tenant_admin(), GRANT_ID))


async def test_an_approval_whose_records_failed_is_finished_by_the_same_command(rig: _Rig) -> None:
    _proposed(rig)
    command = ApproveGrantCommand(_tenant_admin(), GRANT_ID)
    rig.world.fail_commit = "network"
    with bind_tenant(MEMBER_B):
        with pytest.raises(ConnectionError):
            await rig.approve.execute(command)
        assert rig.registry.grant_rows[GRANT_ID].status is GrantStatus.GRANTOR_APPROVED
        rig.world.fail_commit = None
        await rig.approve.execute(command)
    assert [s for s, _ in rig.world.audits] == [MEMBER_B, NETWORK_ID]
    assert len(rig.world.outbox) == 1


# declining


async def test_either_party_may_decline_before_both_approvals(rig: _Rig) -> None:
    _proposed(rig)
    with bind_tenant(OWNER):
        await rig.decline.execute(DeclineGrantCommand(_network_admin(), GRANT_ID))
    assert rig.registry.grant_rows[GRANT_ID].status is GrantStatus.DECLINED
    rig.registry.grant_rows[GRANT_ID] = make_grant(id=GRANT_ID, tenant=MEMBER_B, approved=False)
    with bind_tenant(MEMBER_B):
        await rig.decline.execute(DeclineGrantCommand(_tenant_admin(), GRANT_ID))
    assert rig.registry.grant_rows[GRANT_ID].status is GrantStatus.DECLINED


async def test_after_both_approvals_only_ending_applies(rig: _Rig) -> None:
    rig.grant(tenant=MEMBER_B)
    with bind_tenant(MEMBER_B), pytest.raises(InvalidTransition):
        await rig.decline.execute(DeclineGrantCommand(_tenant_admin(), GRANT_ID))


async def test_a_stranger_cannot_decline(rig: _Rig) -> None:
    _proposed(rig)
    with bind_tenant(MEMBER_C), pytest.raises(NotFound):
        await rig.decline.execute(DeclineGrantCommand(_tenant_admin(MEMBER_C), GRANT_ID))


# ending


async def test_the_grantor_ends_its_grant_and_the_network_scope_follows(rig: _Rig) -> None:
    rig.grant(tenant=MEMBER_B)
    with bind_tenant(MEMBER_B):
        await rig.end.execute(EndGrantCommand(_tenant_admin(), GRANT_ID))
    grant = rig.registry.grant_rows[GRANT_ID]
    assert (grant.status, grant.ended_at) == (GrantStatus.ENDED, AT)
    assert rig.ends.calls == [(NETWORK_ID, MEMBER_B, GrantScope.CAPACITY, GrantEndReason.ENDED, AT)]
    assert rig.events() == [(MEMBER_B, "GrantEnded")]
    order = [
        e
        for e in rig.log
        if e.startswith(("registry:save_grant", "ends:", "tenant:audit", "network:audit"))
    ]
    assert order == [
        "registry:save_grant",
        "ends:end_grant",
        "tenant:audit:EndGrant",
        "network:audit:EndGrant",
    ]


async def test_the_owner_cannot_end_a_members_grant_and_another_member_cannot_either(
    rig: _Rig,
) -> None:
    rig.grant(tenant=MEMBER_B)
    with bind_tenant(OWNER):
        with pytest.raises(NotAllowed):
            await rig.end.execute(EndGrantCommand(_network_admin(), GRANT_ID))
        with pytest.raises(NotFound):
            await rig.end.execute(EndGrantCommand(_tenant_admin(OWNER), GRANT_ID))
    with bind_tenant(MEMBER_C), pytest.raises(NotFound):
        await rig.end.execute(EndGrantCommand(_tenant_admin(MEMBER_C), GRANT_ID))
    assert rig.registry.grant_rows[GRANT_ID].status is GrantStatus.APPROVED


async def test_an_end_that_stopped_after_the_registry_is_finished_by_running_it_again(
    rig: _Rig,
) -> None:
    rig.grant(tenant=MEMBER_B)
    rig.ends.error = ConnectionError("down")
    command = EndGrantCommand(_tenant_admin(), GRANT_ID)
    with bind_tenant(MEMBER_B):
        with pytest.raises(ConnectionError):
            await rig.end.execute(command)
        assert rig.registry.grant_rows[GRANT_ID].status is GrantStatus.ENDED
        rig.clock.advance(timedelta(hours=2))
        rig.ends.error = None
        await rig.end.execute(command)
    assert rig.ends.calls[0][4] == AT  # dated by the first end
    assert len(rig.world.outbox) == 1


async def test_a_grant_that_is_not_yet_approved_can_be_withdrawn_by_ending_it(rig: _Rig) -> None:
    _proposed(rig)
    with bind_tenant(MEMBER_B):
        await rig.end.execute(EndGrantCommand(_tenant_admin(), GRANT_ID))
    assert rig.registry.grant_rows[GRANT_ID].status is GrantStatus.ENDED


async def test_a_grant_that_the_registry_lost_a_race_for_is_a_conflict(rig: _Rig) -> None:
    rig.grant(tenant=MEMBER_B)

    async def racing(grant: Any, *, expected_status: Any) -> None:
        raise Conflict("the registry row is not as expected, so nothing was written")

    rig.registry.save_grant = racing  # type: ignore[method-assign]
    with bind_tenant(MEMBER_B), pytest.raises(Conflict):
        await rig.end.execute(EndGrantCommand(_tenant_admin(), GRANT_ID))
    assert rig.ends.calls == [] and rig.world.outbox == []


# revising and superseding


async def _revise(rig: _Rig, **over: Any) -> str:
    with bind_tenant(MEMBER_B):
        return await rig.revise.execute(ReviseGrantCommand(_tenant_admin(), GRANT_ID, **over))


async def _supersede(rig: _Rig) -> int:
    with bind_tenant(MEMBER_B):
        return await rig.supersede.execute()


async def _approve_both(rig: _Rig, gid: str) -> None:
    with bind_tenant(MEMBER_B):
        await rig.approve.execute(ApproveGrantCommand(_tenant_admin(), gid))
    with bind_tenant(OWNER):
        await rig.approve.execute(ApproveGrantCommand(_network_admin(), gid))


async def test_a_revision_is_the_next_version_and_replaces_the_old_one_when_it_starts(
    rig: _Rig,
) -> None:
    rig.grant(tenant=MEMBER_B)
    new_id = await _revise(rig)
    revised = rig.registry.grant_rows[new_id]
    assert (revised.version, revised.supersedes_id, revised.status) == (
        2,
        GRANT_ID,
        GrantStatus.PROPOSED,
    )
    assert rig.registry.grant_rows[GRANT_ID].status is GrantStatus.APPROVED  # until it is approved
    await _approve_both(rig, new_id)
    assert rig.registry.grant_rows[GRANT_ID].status is GrantStatus.SUPERSEDED
    assert rig.registry.grant_rows[new_id].status is GrantStatus.APPROVED
    ended = [m for _, m in rig.world.outbox if m.event_type == "GrantEnded"]
    assert [m.payload["reason"] for m in ended] == ["superseded"]


async def test_a_revision_that_starts_later_leaves_the_old_grant_until_then(rig: _Rig) -> None:
    rig.grant(tenant=MEMBER_B)
    start = AT + timedelta(days=2)
    new_id = await _revise(rig, effective_from=start)
    await _approve_both(rig, new_id)
    assert rig.registry.grant_rows[GRANT_ID].status is GrantStatus.APPROVED
    assert await _supersede(rig) == 0
    rig.clock.set(start)
    assert await _supersede(rig) == 1
    old = rig.registry.grant_rows[GRANT_ID]
    assert old.status is GrantStatus.SUPERSEDED and old.effective_to == start
    assert await _supersede(rig) == 0  # a repeat changes nothing


async def test_only_an_approved_grant_is_revised_and_only_once_at_a_time(rig: _Rig) -> None:
    _proposed(rig)
    with pytest.raises(InvalidTransition):
        await _revise(rig)
    rig.registry.grant_rows[GRANT_ID] = make_grant(id=GRANT_ID, tenant=MEMBER_B)
    await _revise(rig)
    with pytest.raises(Conflict):
        await _revise(rig)


async def test_a_revision_keeps_the_allowlist_version_it_was_given_when_nothing_widened(
    rig: _Rig,
) -> None:
    rig.grant(tenant=MEMBER_B)
    rig.registry.grant_rows[GRANT_ID] = replace(
        rig.registry.grant_rows[GRANT_ID], allowlist_version=0 + 1
    )
    # the revision is written at the current allowlist version: the same, so allowed
    await _revise(rig)


async def test_only_the_grantors_administrator_revises(rig: _Rig) -> None:
    rig.grant(tenant=MEMBER_B)
    with bind_tenant(OWNER), pytest.raises(NotAllowed):
        await rig.revise.execute(ReviseGrantCommand(_network_admin(), GRANT_ID))
    with bind_tenant(MEMBER_C), pytest.raises(NotFound):
        await rig.revise.execute(ReviseGrantCommand(_tenant_admin(MEMBER_C), GRANT_ID))


# the reads


async def test_a_member_reads_only_its_own_grants_with_the_computed_effectiveness(
    rig: _Rig,
) -> None:
    rig.grant(tenant=MEMBER_B)
    rig.grant(id=rid("grant-c"), tenant=MEMBER_C)
    with bind_tenant(MEMBER_B):
        views = await rig.query.for_tenant(_tenant_admin())
    [view] = views
    assert (view.grant_id, view.scope, view.status, view.effective) == (
        GRANT_ID,
        GrantScope.CAPACITY,
        GrantStatus.APPROVED,
        True,
    )
    assert view.grantor_approved_at is not None and view.owner_approved_at is not None
    assert "acct-" not in repr(view) and MEMBER_C not in repr(view)


async def test_the_owner_reads_every_grant_of_the_network_by_organisation_name(rig: _Rig) -> None:
    rig.grant(tenant=MEMBER_B)
    rig.grant(id=rid("grant-c"), tenant=MEMBER_C)
    with bind_tenant(OWNER):
        views = await rig.query.for_network(_network_admin(), NETWORK_ID)
    assert len(views) == 2
    assert all(MEMBER_B not in repr(v) and MEMBER_C not in repr(v) for v in views)
    assert {v.organisation_name for v in views} == {
        active_tenant(MEMBER_B).display_name,
        active_tenant(MEMBER_C).display_name,
    }


async def test_a_grant_that_has_ended_is_not_effective_and_says_why(rig: _Rig) -> None:
    grant = rig.grant(tenant=MEMBER_B)
    rig.registry.grant_rows[GRANT_ID] = replace(grant, status=GrantStatus.LAPSED, ended_at=NOW)
    with bind_tenant(MEMBER_B):
        [view] = await rig.query.for_tenant(_tenant_admin())
    assert view.effective is False and view.end_reason is GrantEndReason.LAPSED


async def test_the_reads_refuse_other_roles_and_other_networks(rig: _Rig) -> None:
    with bind_tenant(MEMBER_B):
        with pytest.raises(NotAllowed):
            await rig.query.for_tenant(person(MEMBER_B, Role.ADVISOR))
        with pytest.raises(NotAllowed):
            await rig.query.for_network(_tenant_admin(), NETWORK_ID)
        with pytest.raises(NotFound):
            await rig.query.for_network(person(MEMBER_B, Role.NETWORK_ADMIN), NETWORK_ID)


async def test_two_approvals_that_race_both_land_because_the_loser_reads_again(rig: _Rig) -> None:
    """The grantor and the owner approve at the same moment: each reads the proposed grant, and the
    registry lets one write win. The other finds the status moved, reads again and adds its own
    approval to the new state, so neither is lost and no one has to try again."""
    _proposed(rig)
    original = rig.registry.save_grant
    raced = False

    async def racing(grant: Any, *, expected_status: Any) -> None:
        nonlocal raced
        if not raced:
            raced = True
            # the other party's approval lands first
            other = make_grant(id=GRANT_ID, tenant=MEMBER_B, approved=False)
            from diucs.domain.model.network import GrantApprover
            from diucs.domain.rules.grant import approve_grant

            rig.registry.grant_rows[GRANT_ID] = approve_grant(
                other,
                approver=GrantApprover.OWNER,
                approver_tenant_id=OWNER,
                network_owner_tenant_id=OWNER,
                account_ref="acct-owner-0001",
                now=AT,
            )
        await original(grant, expected_status=expected_status)

    rig.registry.save_grant = racing  # type: ignore[method-assign]
    with bind_tenant(MEMBER_B):
        result = await rig.approve.execute(ApproveGrantCommand(_tenant_admin(), GRANT_ID))
    assert result.effective and rig.registry.grant_rows[GRANT_ID].status is GrantStatus.APPROVED
    assert rig.events()[-1] == (MEMBER_B, "GrantEffective")


async def test_an_approval_that_loses_the_race_three_times_is_a_conflict(rig: _Rig) -> None:
    _proposed(rig)

    async def always(grant: Any, *, expected_status: Any) -> None:
        raise Conflict("the registry row is not as expected, so nothing was written")

    rig.registry.save_grant = always  # type: ignore[method-assign]
    with bind_tenant(MEMBER_B), pytest.raises(Conflict):
        await rig.approve.execute(ApproveGrantCommand(_tenant_admin(), GRANT_ID))
    assert rig.world.outbox == []
