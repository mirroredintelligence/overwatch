"""Grant rules: propose, dual approval, end, lapse, revise, supersede, effectiveness (TEN-036).

Sharing is decided here and only here (DEC-132 items 3 and 6, DEC-134 item 6, DEC-136 items 3
and 4). The expected transition table is written out below, not imported from grant.py.
"""

import itertools
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from diucs.domain.errors import Conflict, DomainError, InvalidTransition, NotAllowed, ValidationFailed
from diucs.domain.model.network import (
    Agreement,
    Approval,
    Grant,
    GrantApprover,
    GrantEndReason,
    GrantPurpose,
    GrantScope,
    GrantStatus,
    ListingReason,
    ListingStatus,
    MembershipEndReason,
    MembershipRole,
    MembershipStatus,
    NetworkMembership,
)
from diucs.domain.rules.grant import (
    approve_grant,
    decline_grant,
    effective_grant,
    end_grant,
    end_reason,
    is_effective,
    lapse_grant,
    lapse_grants_for_member,
    may_project,
    propose_grant,
    revise_grant,
    supersede_grant,
    transition_grant,
    was_effective_at,
)

T0 = datetime(2026, 4, 1, 9, 0, tzinfo=UTC)
ONE_US = timedelta(microseconds=1)
OWNER = "tenant-a"  # the network owner
MEMBER = "tenant-b"  # the grantor
OUTSIDER = "tenant-c"
NET = "net-test"
OTHER_NET = "net-other"
OWNER_ACCOUNT = "acct-owner-0001"
GRANTOR_ACCOUNT = "acct-member-0001"
THIRD_ACCOUNT = "acct-member-0002"

AGREEMENT_V1 = Agreement("DSA-2026/14", 1)
AGREEMENT_V2 = Agreement("DSA-2026/14", 2)
_G = GrantStatus


def _at(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


def approval(party: GrantApprover, at: int = 1, grantor_tenant: str = MEMBER) -> Approval:
    if party is GrantApprover.GRANTOR:
        return Approval(GRANTOR_ACCOUNT, grantor_tenant, _at(at))
    return Approval(OWNER_ACCOUNT, OWNER, _at(at))


def make(
    status: GrantStatus,
    *,
    id: str = "grt-1",
    version: int = 1,
    supersedes_id: str | None = None,
    effective_from: datetime | None = None,
    effective_to: datetime | None = None,
    allowlist_version: int = 1,
    agreement: Agreement = AGREEMENT_V1,
    scope: GrantScope = GrantScope.CAPACITY,
    grantor_tenant_id: str = MEMBER,
) -> Grant:
    """A grant in a legal state for the status. Approvals, end fields follow the status."""
    both = status in (_G.APPROVED, _G.ENDED, _G.LAPSED, _G.SUPERSEDED)
    grantor_only = status in (_G.GRANTOR_APPROVED,)
    owner_only = status in (_G.OWNER_APPROVED,)
    ended_states = (_G.DECLINED, _G.ENDED, _G.LAPSED, _G.SUPERSEDED)
    return Grant(
        id=id,
        network_id=NET,
        grantor_tenant_id=grantor_tenant_id,
        scope=scope,
        purpose=GrantPurpose.NETWORK_CAPACITY_VIEW,
        version=version,
        status=status,
        effective_from=effective_from or _at(10),
        effective_to=effective_to,
        agreement=agreement,
        allowlist_version=allowlist_version,
        proposed_by_account_ref=GRANTOR_ACCOUNT,
        proposed_at=T0,
        grantor_approval=(
            approval(GrantApprover.GRANTOR, grantor_tenant=grantor_tenant_id)
            if both or grantor_only
            else None
        ),
        owner_approval=approval(GrantApprover.OWNER) if both or owner_only else None,
        ended_at=_at(50) if status in ended_states else None,
        ended_by_account_ref=OWNER_ACCOUNT if status is _G.ENDED else None,
        supersedes_id=supersedes_id,
    )


def proposed(**kwargs: object) -> Grant:
    return propose_grant(
        id="grt-1",
        network_id=NET,
        grantor_tenant_id=MEMBER,
        scope=GrantScope.CAPACITY,
        purpose=GrantPurpose.NETWORK_CAPACITY_VIEW,
        effective_from=kwargs.get("effective_from", _at(10)),  # type: ignore[arg-type]
        effective_to=kwargs.get("effective_to"),  # type: ignore[arg-type]
        agreement=AGREEMENT_V1,
        allowlist_version=1,
        proposed_by_account_ref=GRANTOR_ACCOUNT,
        proposed_at=T0,
    )


def approve(
    grant: Grant, party: GrantApprover, *, tenant: str | None = None, account: str | None = None,
    at: int = 5,
) -> Grant:
    default_tenant = MEMBER if party is GrantApprover.GRANTOR else OWNER
    default_account = GRANTOR_ACCOUNT if party is GrantApprover.GRANTOR else OWNER_ACCOUNT
    return approve_grant(
        grant,
        approver=party,
        approver_tenant_id=tenant or default_tenant,
        network_owner_tenant_id=OWNER,
        account_ref=account or default_account,
        now=_at(at),
    )


def fully_approved() -> Grant:
    return approve(approve(proposed(), GrantApprover.GRANTOR, at=2), GrantApprover.OWNER, at=3)


def membership_row(
    *,
    status: MembershipStatus = MembershipStatus.ACTIVE,
    member: str = MEMBER,
    network: str = NET,
    left_at: datetime | None = None,
) -> NetworkMembership:
    if status is MembershipStatus.ACTIVE:
        return NetworkMembership(
            id="mem-b", network_id=network, member_tenant_id=member, role=MembershipRole.MEMBER,
            status=status, invited_at=T0, joined_at=_at(1), left_at=None, end_reason=None,
            accepted_agreement=AGREEMENT_V1,
        )
    if status is MembershipStatus.INVITED:
        return NetworkMembership(
            id="mem-b", network_id=network, member_tenant_id=member, role=MembershipRole.MEMBER,
            status=status, invited_at=T0, joined_at=None, left_at=None, end_reason=None,
            accepted_agreement=None,
        )
    return NetworkMembership(
        id="mem-b", network_id=network, member_tenant_id=member, role=MembershipRole.MEMBER,
        status=MembershipStatus.LEFT, invited_at=T0, joined_at=_at(1), left_at=left_at or _at(30),
        end_reason=MembershipEndReason.LEFT, accepted_agreement=AGREEMENT_V1,
    )


def raw_membership(**fields: object) -> NetworkMembership:
    """A membership built without its invariant check: the only way to hold a row the record
    itself refuses, so that a guard in `may_project` can be tested on its own (test 23)."""
    base = membership_row(status=MembershipStatus.ACTIVE)
    values = {
        "id": base.id, "network_id": base.network_id, "member_tenant_id": base.member_tenant_id,
        "role": base.role, "status": base.status, "invited_at": base.invited_at,
        "joined_at": base.joined_at, "left_at": base.left_at, "end_reason": base.end_reason,
        "accepted_agreement": base.accepted_agreement,
    }
    values.update(fields)
    row = object.__new__(NetworkMembership)
    for name, value in values.items():
        object.__setattr__(row, name, value)
    return row


# ---------------------------------------------------------------- 13. propose_grant


def test_propose_builds_a_proposed_version_one_grant_with_no_approvals() -> None:
    grant = proposed()
    assert grant.status is GrantStatus.PROPOSED
    assert grant.version == 1
    assert grant.grantor_approval is None
    assert grant.owner_approval is None
    assert grant.ended_at is None


@pytest.mark.parametrize("scope", ["capacity", ListingReason.DATA_QUALITY])
def test_propose_refuses_a_scope_that_is_not_a_grant_scope(scope: object) -> None:
    with pytest.raises(ValidationFailed) as refused:
        propose_grant(
            id="grt-1", network_id=NET, grantor_tenant_id=MEMBER, scope=scope,  # type: ignore[arg-type]
            purpose=GrantPurpose.NETWORK_CAPACITY_VIEW, effective_from=_at(10), effective_to=None,
            agreement=AGREEMENT_V1, allowlist_version=1,
            proposed_by_account_ref=GRANTOR_ACCOUNT, proposed_at=T0,
        )
    assert refused.value.field == "scope"


def test_propose_refuses_a_purpose_that_is_not_the_capacity_view() -> None:
    with pytest.raises(ValidationFailed) as refused:
        propose_grant(
            id="grt-1", network_id=NET, grantor_tenant_id=MEMBER, scope=GrantScope.CAPACITY,
            purpose="network-capacity-view",  # type: ignore[arg-type]
            effective_from=_at(10), effective_to=None, agreement=AGREEMENT_V1,
            allowlist_version=1, proposed_by_account_ref=GRANTOR_ACCOUNT, proposed_at=T0,
        )
    assert refused.value.field == "purpose"


def test_propose_refuses_a_start_one_microsecond_before_it_is_proposed() -> None:
    with pytest.raises(ValidationFailed) as refused:
        proposed(effective_from=T0 - ONE_US)
    assert refused.value.field == "effective_from"


def test_propose_accepts_a_start_at_the_proposal_instant() -> None:
    assert proposed(effective_from=T0).effective_from == T0


def test_propose_refuses_an_end_equal_to_its_start() -> None:
    with pytest.raises(ValidationFailed) as refused:
        proposed(effective_from=_at(10), effective_to=_at(10))
    assert refused.value.field == "effective_to"


def test_propose_refuses_a_naive_datetime() -> None:
    with pytest.raises(ValidationFailed):
        proposed(effective_from=datetime(2026, 4, 1, 9, 10))


# ---------------------------------------------------------------- 14. transition table

ALLOWED_GRANT = {
    (_G.PROPOSED, _G.GRANTOR_APPROVED),
    (_G.PROPOSED, _G.OWNER_APPROVED),
    (_G.PROPOSED, _G.DECLINED),
    (_G.PROPOSED, _G.ENDED),
    (_G.PROPOSED, _G.LAPSED),
    (_G.GRANTOR_APPROVED, _G.APPROVED),
    (_G.GRANTOR_APPROVED, _G.DECLINED),
    (_G.GRANTOR_APPROVED, _G.ENDED),
    (_G.GRANTOR_APPROVED, _G.LAPSED),
    (_G.OWNER_APPROVED, _G.APPROVED),
    (_G.OWNER_APPROVED, _G.DECLINED),
    (_G.OWNER_APPROVED, _G.ENDED),
    (_G.OWNER_APPROVED, _G.LAPSED),
    (_G.APPROVED, _G.ENDED),
    (_G.APPROVED, _G.LAPSED),
    (_G.APPROVED, _G.SUPERSEDED),
}


@pytest.mark.parametrize(("current", "target"), list(itertools.product(list(GrantStatus), repeat=2)))
def test_every_grant_transition_pair_is_allowed_or_refused(
    current: GrantStatus, target: GrantStatus
) -> None:
    if (current, target) in ALLOWED_GRANT:
        assert transition_grant(current, target) is target
    else:
        with pytest.raises(InvalidTransition):
            transition_grant(current, target)


@pytest.mark.parametrize("terminal", [_G.DECLINED, _G.ENDED, _G.LAPSED, _G.SUPERSEDED])
def test_terminal_grant_statuses_have_no_way_out(terminal: GrantStatus) -> None:
    assert [t for t in GrantStatus if (terminal, t) in ALLOWED_GRANT] == []


def test_a_member_of_another_enum_with_the_same_value_is_refused_by_transition() -> None:
    with pytest.raises(ValidationFailed) as refused:
        transition_grant(ListingStatus.DECLINED, GrantStatus.DECLINED)  # type: ignore[arg-type]
    assert "declined" not in str(refused.value)
    with pytest.raises(ValidationFailed):
        transition_grant(GrantStatus.PROPOSED, "approved")  # type: ignore[arg-type]


# ---------------------------------------------------------------- 15. dual approval


def test_grantor_then_owner_gives_approved_with_both_approvals() -> None:
    grant = fully_approved()
    assert grant.status is GrantStatus.APPROVED
    assert grant.grantor_approval is not None and grant.owner_approval is not None


def test_owner_then_grantor_gives_the_same_status() -> None:
    grant = approve(approve(proposed(), GrantApprover.OWNER, at=2), GrantApprover.GRANTOR, at=3)
    assert grant.status is GrantStatus.APPROVED


def test_one_approval_never_gives_approved() -> None:
    once = approve(proposed(), GrantApprover.GRANTOR)
    assert once.status is GrantStatus.GRANTOR_APPROVED
    assert once.owner_approval is None
    twice = approve(proposed(), GrantApprover.OWNER)
    assert twice.status is GrantStatus.OWNER_APPROVED
    assert twice.grantor_approval is None


def test_the_grantor_approval_by_the_owner_tenant_is_refused() -> None:
    with pytest.raises(NotAllowed):
        approve(proposed(), GrantApprover.GRANTOR, tenant=OWNER, account=OWNER_ACCOUNT)


def test_the_owner_approval_by_a_third_tenant_is_refused() -> None:
    with pytest.raises(NotAllowed):
        approve(proposed(), GrantApprover.OWNER, tenant=OUTSIDER, account=THIRD_ACCOUNT)


def test_the_same_account_approving_twice_returns_the_grant_unchanged() -> None:
    once = approve(proposed(), GrantApprover.GRANTOR, at=2)
    again = approve(once, GrantApprover.GRANTOR, at=9)
    assert again == once


def test_a_different_account_for_the_same_party_is_a_conflict() -> None:
    once = approve(proposed(), GrantApprover.GRANTOR, at=2)
    with pytest.raises(Conflict):
        approve(once, GrantApprover.GRANTOR, account=THIRD_ACCOUNT, at=3)


def test_when_grantor_and_owner_are_one_tenant_the_same_account_twice_is_a_conflict() -> None:
    same_tenant = make(_G.GRANTOR_APPROVED, grantor_tenant_id=OWNER)
    with pytest.raises(Conflict):
        approve_grant(
            same_tenant,
            approver=GrantApprover.OWNER,
            approver_tenant_id=OWNER,
            network_owner_tenant_id=OWNER,
            account_ref=GRANTOR_ACCOUNT,  # the account that already approved as grantor
            now=_at(7),
        )


def test_when_grantor_and_owner_are_one_tenant_two_people_give_approved() -> None:
    same_tenant = make(_G.PROPOSED, grantor_tenant_id=OWNER)
    first = approve_grant(
        same_tenant, approver=GrantApprover.GRANTOR, approver_tenant_id=OWNER,
        network_owner_tenant_id=OWNER, account_ref=GRANTOR_ACCOUNT, now=_at(2),
    )
    second = approve_grant(
        first, approver=GrantApprover.OWNER, approver_tenant_id=OWNER,
        network_owner_tenant_id=OWNER, account_ref=THIRD_ACCOUNT, now=_at(3),
    )
    assert second.status is GrantStatus.APPROVED
    assert second.version == 1


def test_approving_does_not_change_the_version() -> None:
    assert fully_approved().version == proposed().version == 1


@pytest.mark.parametrize("terminal", [_G.DECLINED, _G.ENDED, _G.LAPSED, _G.SUPERSEDED])
def test_a_terminal_grant_cannot_be_approved(terminal: GrantStatus) -> None:
    with pytest.raises(InvalidTransition):
        approve(make(terminal), GrantApprover.OWNER)


# ---------------------------------------------------------------- 16. is_effective boundaries


def test_effective_starts_at_effective_from_inclusive_and_ends_at_effective_to_exclusive() -> None:
    grant = make(_G.APPROVED, effective_from=_at(10), effective_to=_at(100))
    assert is_effective(grant, _at(10) - ONE_US) is False
    assert is_effective(grant, _at(10)) is True
    assert is_effective(grant, _at(100) - ONE_US) is True
    assert is_effective(grant, _at(100)) is False


@pytest.mark.parametrize("status", list(GrantStatus))
def test_only_an_approved_grant_is_effective(status: GrantStatus) -> None:
    grant = make(status, effective_to=None)
    assert is_effective(grant, _at(500)) is (status is GrantStatus.APPROVED)


def test_an_ended_grant_is_not_effective_once_ended() -> None:
    ended = end_grant(fully_approved(), by_tenant_id=MEMBER, account_ref=GRANTOR_ACCOUNT, now=_at(40))
    assert is_effective(ended, _at(41)) is False
    assert is_effective(make(_G.ENDED), _at(51)) is False


def test_with_no_end_date_it_is_effective_a_year_later() -> None:
    grant = make(_G.APPROVED, effective_from=_at(10), effective_to=None)
    assert is_effective(grant, _at(10) + timedelta(days=365)) is True


def test_effectiveness_is_judged_on_the_real_instant_across_the_london_clock_change() -> None:
    from zoneinfo import ZoneInfo

    london = ZoneInfo("Europe/London")
    start = datetime(2026, 10, 25, 0, 30, tzinfo=UTC).astimezone(london)
    end = datetime(2026, 10, 25, 1, 30, tzinfo=UTC).astimezone(london)
    grant = make(_G.APPROVED, effective_from=start, effective_to=end)
    inside = datetime(2026, 10, 25, 1, 0, tzinfo=UTC).astimezone(london)
    assert is_effective(grant, inside) is True
    assert is_effective(grant, end) is False


# ---------------------------------------------------------------- 17. end by the grantor


def test_end_by_the_grantor_stops_future_sharing_and_keeps_the_history() -> None:
    grant = fully_approved()
    ended = end_grant(grant, by_tenant_id=MEMBER, account_ref=GRANTOR_ACCOUNT, now=_at(40))
    assert ended.status is GrantStatus.ENDED
    assert ended.ended_at == _at(40)
    assert ended.ended_by_account_ref == GRANTOR_ACCOUNT
    assert ended.grantor_approval == grant.grantor_approval
    assert ended.owner_approval == grant.owner_approval
    assert ended.effective_from == grant.effective_from
    assert ended.effective_to == grant.effective_to
    assert is_effective(ended, _at(40)) is False
    assert was_effective_at(ended, _at(40) - ONE_US) is True
    assert was_effective_at(ended, _at(40)) is False


def test_end_by_the_owner_tenant_is_refused_the_owner_removes_a_member_instead() -> None:
    with pytest.raises(NotAllowed):
        end_grant(fully_approved(), by_tenant_id=OWNER, account_ref=OWNER_ACCOUNT, now=_at(40))


def test_end_by_a_third_tenant_is_refused() -> None:
    with pytest.raises(NotAllowed):
        end_grant(fully_approved(), by_tenant_id=OUTSIDER, account_ref=THIRD_ACCOUNT, now=_at(40))


def test_ending_an_ended_grant_returns_it_unchanged() -> None:
    ended = end_grant(fully_approved(), by_tenant_id=MEMBER, account_ref=GRANTOR_ACCOUNT, now=_at(40))
    assert end_grant(ended, by_tenant_id=MEMBER, account_ref=GRANTOR_ACCOUNT, now=_at(41)) == ended


def test_ending_a_declined_grant_is_refused() -> None:
    with pytest.raises(InvalidTransition):
        end_grant(make(_G.DECLINED), by_tenant_id=MEMBER, account_ref=GRANTOR_ACCOUNT, now=_at(60))


def test_ending_a_proposed_grant_gives_ended_and_it_was_never_effective() -> None:
    ended = end_grant(proposed(), by_tenant_id=MEMBER, account_ref=GRANTOR_ACCOUNT, now=_at(5))
    assert ended.status is GrantStatus.ENDED
    for minute in range(0, 120, 7):
        assert was_effective_at(ended, _at(minute)) is False


# ---------------------------------------------------------------- 18. decline


@pytest.mark.parametrize(
    "start",
    [
        lambda: proposed(),
        lambda: approve(proposed(), GrantApprover.GRANTOR, at=2),
        lambda: approve(proposed(), GrantApprover.OWNER, at=2),
    ],
    ids=["proposed", "grantor-approved", "owner-approved"],
)
@pytest.mark.parametrize("party", [MEMBER, OWNER], ids=["grantor", "owner"])
def test_either_party_may_decline_before_approval(start: object, party: str) -> None:
    declined = decline_grant(
        start(), by_tenant_id=party, network_owner_tenant_id=OWNER,  # type: ignore[operator]
        account_ref=OWNER_ACCOUNT, now=_at(30),
    )
    assert declined.status is GrantStatus.DECLINED
    assert declined.ended_at == _at(30)


def test_declining_after_approval_is_refused() -> None:
    with pytest.raises(InvalidTransition):
        decline_grant(
            fully_approved(), by_tenant_id=OWNER, network_owner_tenant_id=OWNER,
            account_ref=OWNER_ACCOUNT, now=_at(30),
        )


def test_a_third_tenant_cannot_decline() -> None:
    with pytest.raises(NotAllowed):
        decline_grant(
            proposed(), by_tenant_id=OUTSIDER, network_owner_tenant_id=OWNER,
            account_ref=THIRD_ACCOUNT, now=_at(30),
        )


# ---------------------------------------------------------------- 19. lapse


@pytest.mark.parametrize(
    "status", [_G.PROPOSED, _G.GRANTOR_APPROVED, _G.OWNER_APPROVED, _G.APPROVED]
)
def test_lapse_from_each_live_status_keeps_the_approvals(status: GrantStatus) -> None:
    grant = make(status)
    lapsed = lapse_grant(grant, now=_at(70))
    assert lapsed.status is GrantStatus.LAPSED
    assert lapsed.ended_at == _at(70)
    assert lapsed.grantor_approval == grant.grantor_approval
    assert lapsed.owner_approval == grant.owner_approval


@pytest.mark.parametrize("status", [_G.DECLINED, _G.ENDED, _G.LAPSED, _G.SUPERSEDED])
def test_lapse_of_a_terminal_grant_is_refused(status: GrantStatus) -> None:
    with pytest.raises(InvalidTransition):
        lapse_grant(make(status), now=_at(70))


def test_lapse_for_a_leaving_member_touches_only_its_live_grants_in_that_network() -> None:
    live_one = make(_G.APPROVED, id="grt-a")
    live_two = make(_G.PROPOSED, id="grt-b")
    ended = make(_G.ENDED, id="grt-c")
    other_member = make(_G.APPROVED, id="grt-d", grantor_tenant_id=OUTSIDER)
    other_network = replace(make(_G.APPROVED, id="grt-e"), network_id=OTHER_NET)
    grants = [other_member, other_network, ended, live_one, live_two]

    lapsed = lapse_grants_for_member(
        grants, membership_row(status=MembershipStatus.LEFT), now=_at(80)
    )

    assert [g.id for g in lapsed] == ["grt-a", "grt-b"]
    assert all(g.status is GrantStatus.LAPSED for g in lapsed)
    assert all(g.ended_at == _at(80) for g in lapsed)


# ---------------------------------------------------------------- 20. revision


def test_revising_an_approved_grant_gives_a_proposed_next_version() -> None:
    current = fully_approved()
    successor = revise_grant(
        current, new_id="grt-2", effective_from=_at(90), effective_to=None,
        agreement=AGREEMENT_V1, allowlist_version=1,
        proposed_by_account_ref=GRANTOR_ACCOUNT, now=_at(60),
    )
    assert successor.status is GrantStatus.PROPOSED
    assert successor.version == current.version + 1
    assert successor.supersedes_id == current.id
    assert successor.scope is current.scope
    assert successor.purpose is current.purpose
    assert successor.grantor_tenant_id == current.grantor_tenant_id
    assert successor.network_id == current.network_id


@pytest.mark.parametrize("status", [s for s in GrantStatus if s is not _G.APPROVED])
def test_revising_anything_but_an_approved_grant_is_refused(status: GrantStatus) -> None:
    with pytest.raises(InvalidTransition):
        revise_grant(
            make(status), new_id="grt-2", effective_from=_at(90), effective_to=None,
            agreement=AGREEMENT_V1, allowlist_version=1,
            proposed_by_account_ref=GRANTOR_ACCOUNT, now=_at(60),
        )


def test_widening_the_allowlist_needs_a_higher_agreement_version() -> None:
    current = fully_approved()
    with pytest.raises(ValidationFailed):
        revise_grant(
            current, new_id="grt-2", effective_from=_at(90), effective_to=None,
            agreement=AGREEMENT_V1, allowlist_version=2,
            proposed_by_account_ref=GRANTOR_ACCOUNT, now=_at(60),
        )
    widened = revise_grant(
        current, new_id="grt-2", effective_from=_at(90), effective_to=None,
        agreement=AGREEMENT_V2, allowlist_version=2,
        proposed_by_account_ref=GRANTOR_ACCOUNT, now=_at(60),
    )
    assert widened.allowlist_version == 2


def test_a_revision_cannot_be_backdated() -> None:
    with pytest.raises(ValidationFailed):
        revise_grant(
            fully_approved(), new_id="grt-2", effective_from=_at(59), effective_to=None,
            agreement=AGREEMENT_V1, allowlist_version=1,
            proposed_by_account_ref=GRANTOR_ACCOUNT, now=_at(60),
        )


# ---------------------------------------------------------------- 21. supersession

SUCCESSOR_START = 60
SUPERSEDE_NOW = 70


def _successor(old: Grant, **kwargs: object) -> Grant:
    values: dict[str, object] = {
        "id": "grt-2",
        "version": old.version + 1,
        "supersedes_id": old.id,
        "effective_from": _at(SUCCESSOR_START),
    }
    values.update(kwargs)
    return make(_G.APPROVED, **values)  # type: ignore[arg-type]


def test_supersession_ends_the_old_grant_at_the_successor_start() -> None:
    old = make(_G.APPROVED, effective_from=_at(10))
    successor = _successor(old)
    superseded = supersede_grant(old, successor, now=_at(SUPERSEDE_NOW))
    assert superseded.status is GrantStatus.SUPERSEDED
    assert superseded.effective_to == successor.effective_from
    assert superseded.ended_at == _at(SUPERSEDE_NOW)


def test_supersession_leaves_no_overlap_and_no_gap_in_effect() -> None:
    old = make(_G.APPROVED, effective_from=_at(10))
    superseded = supersede_grant(old, _successor(old), now=_at(SUPERSEDE_NOW))
    boundary = _at(SUCCESSOR_START)
    assert is_effective(superseded, boundary - ONE_US) is False
    assert was_effective_at(superseded, boundary - ONE_US) is True
    assert was_effective_at(superseded, boundary) is False


def test_supersession_before_the_successor_starts_is_a_conflict() -> None:
    old = make(_G.APPROVED, effective_from=_at(10))
    with pytest.raises(Conflict):
        supersede_grant(old, _successor(old), now=_at(SUCCESSOR_START) - ONE_US)


def test_a_gap_before_the_successor_is_a_conflict() -> None:
    old = make(_G.APPROVED, effective_from=_at(10), effective_to=_at(40))
    with pytest.raises(Conflict):
        supersede_grant(old, _successor(old), now=_at(SUPERSEDE_NOW))


@pytest.mark.parametrize(
    "bad",
    [{"version": 3}, {"supersedes_id": "grt-9"}, {"status_is_proposed": True}],
    ids=["wrong-version", "wrong-supersedes-id", "not-approved"],
)
def test_a_successor_that_does_not_follow_is_refused(bad: dict[str, object]) -> None:
    old = make(_G.APPROVED, effective_from=_at(10))
    if bad.get("status_is_proposed"):
        successor = make(_G.PROPOSED, id="grt-2", version=2, supersedes_id=old.id,
                         effective_from=_at(SUCCESSOR_START))
    else:
        successor = _successor(old, **bad)
    with pytest.raises((Conflict, ValidationFailed, InvalidTransition)):
        supersede_grant(old, successor, now=_at(SUPERSEDE_NOW))


def test_only_an_approved_grant_can_be_superseded() -> None:
    old = make(_G.ENDED, effective_from=_at(10))
    with pytest.raises(InvalidTransition):
        supersede_grant(old, _successor(old), now=_at(SUPERSEDE_NOW))


def test_a_successor_for_another_scope_is_refused() -> None:
    old = make(_G.APPROVED, effective_from=_at(10))
    with pytest.raises(ValidationFailed):
        supersede_grant(old, _successor(old, scope=GrantScope.DIRECTORY), now=_at(SUPERSEDE_NOW))


# ---------------------------------------------------------------- 22. effective_grant


def test_effective_grant_returns_the_highest_effective_version() -> None:
    v1 = make(_G.APPROVED, id="grt-1", version=1, effective_from=_at(10), effective_to=_at(60))
    v2 = make(_G.APPROVED, id="grt-2", version=2, effective_from=_at(60), supersedes_id="grt-1")
    found = effective_grant(
        [v1, v2], network_id=NET, grantor_tenant_id=MEMBER, scope=GrantScope.CAPACITY, now=_at(70)
    )
    assert found == v2


def test_effective_grant_is_none_when_nothing_is_effective() -> None:
    proposed_only = make(_G.PROPOSED)
    assert effective_grant(
        [proposed_only], network_id=NET, grantor_tenant_id=MEMBER,
        scope=GrantScope.CAPACITY, now=_at(70),
    ) is None


def test_effective_grant_ignores_other_grantors_scopes_and_networks() -> None:
    right = make(_G.APPROVED, id="grt-1")
    others = [
        make(_G.APPROVED, id="grt-x", grantor_tenant_id=OUTSIDER, version=9),
        make(_G.APPROVED, id="grt-y", scope=GrantScope.DIRECTORY, version=9),
        replace(make(_G.APPROVED, id="grt-z", version=9), network_id=OTHER_NET),
    ]
    found = effective_grant(
        [*others, right], network_id=NET, grantor_tenant_id=MEMBER,
        scope=GrantScope.CAPACITY, now=_at(70),
    )
    assert found == right


def test_effective_grant_refuses_a_scope_that_is_not_a_grant_scope() -> None:
    with pytest.raises(ValidationFailed):
        effective_grant(
            [], network_id=NET, grantor_tenant_id=MEMBER, scope="capacity",  # type: ignore[arg-type]
            now=_at(70),
        )


# ---------------------------------------------------------------- 23. may_project


def test_may_project_is_true_when_every_condition_holds() -> None:
    assert may_project(fully_approved(), membership_row(), _at(70)) is True


def test_may_project_is_false_when_the_grant_is_not_effective() -> None:
    assert may_project(fully_approved(), membership_row(), _at(5)) is False


def test_may_project_is_false_for_a_left_membership() -> None:
    row = membership_row(status=MembershipStatus.LEFT, left_at=_at(30))
    assert may_project(fully_approved(), row, _at(70)) is False


def test_may_project_is_false_for_an_invited_membership() -> None:
    assert may_project(fully_approved(), membership_row(status=MembershipStatus.INVITED), _at(70)) is False


def test_may_project_is_false_when_the_membership_has_a_leave_date() -> None:
    # An active row cannot hold a leave date (the record refuses it), so this row is built raw:
    # the projector must refuse it on its own, not rely on the record's check.
    row = raw_membership(left_at=_at(30))
    assert may_project(fully_approved(), row, _at(70)) is False


def test_may_project_is_false_for_another_tenants_membership() -> None:
    row = membership_row(member=OUTSIDER)
    assert may_project(fully_approved(), row, _at(70)) is False


def test_may_project_is_false_for_a_membership_of_another_network() -> None:
    row = membership_row(network=OTHER_NET)
    assert may_project(fully_approved(), row, _at(70)) is False


def test_end_reason_maps_the_three_end_statuses_and_nothing_else() -> None:
    assert end_reason(make(_G.ENDED)) is GrantEndReason.ENDED
    assert end_reason(make(_G.LAPSED)) is GrantEndReason.LAPSED
    assert end_reason(make(_G.SUPERSEDED)) is GrantEndReason.SUPERSEDED
    for status in (_G.PROPOSED, _G.GRANTOR_APPROVED, _G.OWNER_APPROVED, _G.APPROVED, _G.DECLINED):
        assert end_reason(make(status)) is None


def test_approver_values_are_the_grantor_and_owner() -> None:
    assert [a.value for a in GrantApprover] == ["grantor", "owner"]


def test_may_project_refuses_a_grant_status_where_a_membership_status_is_required() -> None:
    # Lesson L3: GrantStatus.APPROVED is not a MembershipStatus, whatever its value says.
    with pytest.raises(ValidationFailed):
        may_project(fully_approved(), raw_membership(status=GrantStatus.APPROVED), _at(70))  # type: ignore[arg-type]


# ---------------------------------------------------------------- 24. property machine


@settings(max_examples=60, deadline=None, stateful_step_count=25)
class GrantLifecycle(RuleBasedStateMachine):
    """Random sequences of the grant rules. Each step either applies or is refused with a
    domain error (state unchanged); the invariants must hold after every step."""

    def __init__(self) -> None:
        super().__init__()
        self.clock = 0
        self.current: Grant | None = None
        self.history: list[Grant] = []

    def _now(self, step: int) -> datetime:
        self.clock += step
        return _at(self.clock)

    def _try(self, action: object) -> None:
        try:
            result = action()  # type: ignore[operator]
        except DomainError:
            return
        self.current = result  # type: ignore[assignment]
        self.history.append(result)  # type: ignore[arg-type]

    @rule(offset=st.integers(min_value=0, max_value=400))
    def propose(self, offset: int) -> None:
        if self.current is not None:
            return
        now = self._now(1)
        self._try(lambda: propose_grant(
            id="grt-1", network_id=NET, grantor_tenant_id=MEMBER, scope=GrantScope.CAPACITY,
            purpose=GrantPurpose.NETWORK_CAPACITY_VIEW, effective_from=now + timedelta(minutes=offset),
            effective_to=None, agreement=AGREEMENT_V1, allowlist_version=1,
            proposed_by_account_ref=GRANTOR_ACCOUNT, proposed_at=now,
        ))

    @rule(party=st.sampled_from(list(GrantApprover)), step=st.integers(min_value=0, max_value=5))
    def approve_one(self, party: GrantApprover, step: int) -> None:
        if self.current is None:
            return
        now = self._now(step)
        grant = self.current
        self._try(lambda: approve_grant(
            grant, approver=party,
            approver_tenant_id=MEMBER if party is GrantApprover.GRANTOR else OWNER,
            network_owner_tenant_id=OWNER,
            account_ref=GRANTOR_ACCOUNT if party is GrantApprover.GRANTOR else OWNER_ACCOUNT,
            now=now,
        ))

    @rule(step=st.integers(min_value=0, max_value=30))
    def end(self, step: int) -> None:
        if self.current is None:
            return
        now = self._now(step)
        grant = self.current
        self._try(lambda: end_grant(grant, by_tenant_id=MEMBER, account_ref=GRANTOR_ACCOUNT, now=now))

    @rule(step=st.integers(min_value=0, max_value=30))
    def decline(self, step: int) -> None:
        if self.current is None:
            return
        now = self._now(step)
        grant = self.current
        self._try(lambda: decline_grant(
            grant, by_tenant_id=OWNER, network_owner_tenant_id=OWNER,
            account_ref=OWNER_ACCOUNT, now=now,
        ))

    @rule(step=st.integers(min_value=0, max_value=30))
    def lapse(self, step: int) -> None:
        if self.current is None:
            return
        now = self._now(step)
        grant = self.current
        self._try(lambda: lapse_grant(grant, now=now))

    @invariant()
    def approved_means_both_approvals(self) -> None:
        if self.current is not None and self.current.status is GrantStatus.APPROVED:
            assert self.current.grantor_approval is not None
            assert self.current.owner_approval is not None

    @invariant()
    def terminal_statuses_never_change(self) -> None:
        terminal = [g for g in self.history if g.status in (_G.DECLINED, _G.ENDED, _G.LAPSED, _G.SUPERSEDED)]
        if terminal:
            first_terminal = terminal[0]
            assert self.current == first_terminal

    @invariant()
    def effective_implies_approved_and_both_approvals(self) -> None:
        if self.current is None:
            return
        for minute in (0, 10, 50, 200, 400):
            instant = _at(minute)
            if is_effective(self.current, instant):
                assert self.current.status is GrantStatus.APPROVED
            if was_effective_at(self.current, instant):
                assert self.current.grantor_approval is not None
                assert self.current.owner_approval is not None

    @invariant()
    def the_end_instant_is_never_after_the_end_date(self) -> None:
        if self.current is None or self.current.effective_to is None:
            return
        for minute in (0, 50, 100, 400):
            if was_effective_at(self.current, _at(minute)):
                assert _at(minute) < self.current.effective_to


TestGrantLifecycle = GrantLifecycle.TestCase
