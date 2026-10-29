"""Network listing rules: request, admission, suspension, presentation, and what a listing shows
(TEN-036; DEC-132 item 3, DEC-136 items 3 and 4, hazard H-N12).

The listing is the owner's decision on one member's service (DEC-136 item 3). The expected
transition table is written out here, not imported from listing.py.
"""

import itertools
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from diucs.domain.errors import Conflict, InvalidTransition, NotAllowed, ValidationFailed
from diucs.domain.model.network import (
    Agreement,
    Approval,
    Grant,
    GrantPurpose,
    GrantScope,
    GrantStatus,
    Listing,
    ListingReason,
    ListingStatus,
    MembershipEndReason,
    MembershipRole,
    MembershipStatus,
    NetworkMembership,
)
from diucs.domain.rules.listing import (
    ListingPresentation,
    admit_listing,
    decline_listing,
    listing_presentation,
    may_project_listing,
    reinstate_listing,
    request_listing,
    shows_on_board,
    suspend_listing,
    transition_listing,
    visible_scopes,
    withdraw_for_leave,
    withdraw_listing,
)

T0 = datetime(2026, 4, 1, 9, 0, tzinfo=UTC)
OWNER = "tenant-a"
MEMBER = "tenant-b"
OUTSIDER = "tenant-c"
NET = "net-test"
OTHER_NET = "net-other"
OWNER_ACCOUNT = "acct-owner-0001"
MEMBER_ACCOUNT = "acct-member-0001"
AGREEMENT = Agreement("DSA-2026/14", 1)
_L = ListingStatus


def _at(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


def listing(
    status: ListingStatus = _L.PENDING,
    *,
    id: str = "lst-1",
    source: str = MEMBER,
    network: str = NET,
    service: str = "svc-ucr-west",
    reason: ListingReason | None = None,
) -> Listing:
    """A listing in a legal state for its status."""
    decided = status in (_L.ADMITTED, _L.DECLINED, _L.SUSPENDED, _L.WITHDRAWN)
    decided_by = None
    if status in (_L.ADMITTED, _L.DECLINED, _L.SUSPENDED):
        decided_by = OWNER_ACCOUNT
    if status in (_L.DECLINED, _L.SUSPENDED) and reason is None:
        reason = ListingReason.DATA_QUALITY
    if status is _L.ADMITTED:
        reason = None
    return Listing(
        id=id,
        network_id=network,
        source_tenant_id=source,
        source_service_id=service,
        status=status,
        requested_at=T0,
        decided_at=_at(5) if decided else None,
        decided_by_account_ref=decided_by,
        reason=reason if status in (_L.DECLINED, _L.SUSPENDED) else None,
    )


def row(
    status: MembershipStatus = MembershipStatus.ACTIVE,
    *,
    member: str = MEMBER,
    network: str = NET,
) -> NetworkMembership:
    if status is MembershipStatus.ACTIVE:
        return NetworkMembership(
            id="mem-b", network_id=network, member_tenant_id=member, role=MembershipRole.MEMBER,
            status=status, invited_at=T0, joined_at=_at(1), left_at=None, end_reason=None,
            accepted_agreement=AGREEMENT,
        )
    if status is MembershipStatus.LEFT:
        return NetworkMembership(
            id="mem-b", network_id=network, member_tenant_id=member, role=MembershipRole.MEMBER,
            status=status, invited_at=T0, joined_at=_at(1), left_at=_at(30),
            end_reason=MembershipEndReason.LEFT, accepted_agreement=AGREEMENT,
        )
    return NetworkMembership(
        id="mem-b", network_id=network, member_tenant_id=member, role=MembershipRole.MEMBER,
        status=MembershipStatus.INVITED, invited_at=T0, joined_at=None, left_at=None,
        end_reason=None, accepted_agreement=None,
    )


def grant(
    status: GrantStatus = GrantStatus.APPROVED,
    *,
    grantor: str = MEMBER,
    network: str = NET,
    scope: GrantScope = GrantScope.CAPACITY,
    effective_from: int = 10,
    effective_to: int | None = None,
    id: str = "grt-1",
) -> Grant:
    approved = status is GrantStatus.APPROVED
    ended = status in (GrantStatus.DECLINED, GrantStatus.ENDED, GrantStatus.LAPSED, GrantStatus.SUPERSEDED)
    return Grant(
        id=id,
        network_id=network,
        grantor_tenant_id=grantor,
        scope=scope,
        purpose=GrantPurpose.NETWORK_CAPACITY_VIEW,
        version=1,
        status=status,
        effective_from=_at(effective_from),
        effective_to=_at(effective_to) if effective_to is not None else None,
        agreement=AGREEMENT,
        allowlist_version=1,
        proposed_by_account_ref=MEMBER_ACCOUNT,
        proposed_at=T0,
        grantor_approval=Approval(MEMBER_ACCOUNT, grantor, _at(2)) if approved or status is GrantStatus.GRANTOR_APPROVED else None,
        owner_approval=Approval(OWNER_ACCOUNT, OWNER, _at(3)) if approved or status is GrantStatus.OWNER_APPROVED else None,
        ended_at=_at(50) if ended else None,
        ended_by_account_ref=OWNER_ACCOUNT if status is GrantStatus.ENDED else None,
        supersedes_id=None,
    )


# ---------------------------------------------------------------- 26. transitions

ALLOWED_LISTING = {
    (_L.PENDING, _L.ADMITTED),
    (_L.PENDING, _L.DECLINED),
    (_L.PENDING, _L.WITHDRAWN),
    (_L.ADMITTED, _L.SUSPENDED),
    (_L.ADMITTED, _L.WITHDRAWN),
    (_L.SUSPENDED, _L.ADMITTED),
    (_L.SUSPENDED, _L.WITHDRAWN),
}


@pytest.mark.parametrize(("current", "target"), list(itertools.product(list(ListingStatus), repeat=2)))
def test_every_listing_transition_pair_is_allowed_or_refused(
    current: ListingStatus, target: ListingStatus
) -> None:
    if (current, target) in ALLOWED_LISTING:
        assert transition_listing(current, target) is target
    else:
        with pytest.raises(InvalidTransition):
            transition_listing(current, target)


@pytest.mark.parametrize("terminal", [_L.DECLINED, _L.WITHDRAWN])
def test_declined_and_withdrawn_are_terminal(terminal: ListingStatus) -> None:
    assert [t for t in ListingStatus if (terminal, t) in ALLOWED_LISTING] == []


def test_a_grant_status_is_refused_as_a_listing_status() -> None:
    with pytest.raises(ValidationFailed) as refused:
        transition_listing(GrantStatus.DECLINED, ListingStatus.ADMITTED)  # type: ignore[arg-type]
    assert "declined" not in str(refused.value)


# ---------------------------------------------------------------- 27. authority and reasons


@pytest.mark.parametrize("by", [MEMBER, OUTSIDER])
def test_only_the_owner_admits_and_the_others_are_refused(by: str) -> None:
    with pytest.raises(NotAllowed):
        admit_listing(listing(), by_tenant_id=by, owner_tenant_id=OWNER, account_ref=OWNER_ACCOUNT, now=_at(6))


@pytest.mark.parametrize("by", [MEMBER, OUTSIDER])
def test_the_source_and_a_third_tenant_cannot_suspend_or_reinstate(by: str) -> None:
    with pytest.raises(NotAllowed):
        suspend_listing(
            listing(_L.ADMITTED), by_tenant_id=by, owner_tenant_id=OWNER,
            reason=ListingReason.DATA_QUALITY, account_ref=OWNER_ACCOUNT, now=_at(6),
        )
    with pytest.raises(NotAllowed):
        reinstate_listing(
            listing(_L.SUSPENDED), by_tenant_id=by, owner_tenant_id=OWNER,
            account_ref=OWNER_ACCOUNT, now=_at(6),
        )


@pytest.mark.parametrize("by", [MEMBER, OUTSIDER])
def test_the_source_and_a_third_tenant_cannot_decline(by: str) -> None:
    with pytest.raises(NotAllowed):
        decline_listing(
            listing(), by_tenant_id=by, owner_tenant_id=OWNER,
            reason=ListingReason.OTHER, account_ref=OWNER_ACCOUNT, now=_at(6),
        )


def test_the_owner_admits_suspends_reinstates_and_declines() -> None:
    admitted = admit_listing(listing(), by_tenant_id=OWNER, owner_tenant_id=OWNER, account_ref=OWNER_ACCOUNT, now=_at(6))
    assert admitted.status is _L.ADMITTED
    assert admitted.decided_by_account_ref == OWNER_ACCOUNT
    assert admitted.decided_at == _at(6)
    assert admitted.reason is None

    suspended = suspend_listing(
        admitted, by_tenant_id=OWNER, owner_tenant_id=OWNER,
        reason=ListingReason.SAFETY_CONCERN, account_ref=OWNER_ACCOUNT, now=_at(7),
    )
    assert suspended.status is _L.SUSPENDED
    assert suspended.reason is ListingReason.SAFETY_CONCERN

    back = reinstate_listing(suspended, by_tenant_id=OWNER, owner_tenant_id=OWNER, account_ref=OWNER_ACCOUNT, now=_at(8))
    assert back.status is _L.ADMITTED
    assert back.reason is None

    declined = decline_listing(
        listing(), by_tenant_id=OWNER, owner_tenant_id=OWNER,
        reason=ListingReason.OUTSIDE_AREA, account_ref=OWNER_ACCOUNT, now=_at(9),
    )
    assert declined.status is _L.DECLINED
    assert declined.reason is ListingReason.OUTSIDE_AREA


@pytest.mark.parametrize("reason", [None, ListingStatus.DECLINED, "data-quality"])
def test_decline_and_suspend_need_a_listing_reason_code(reason: object) -> None:
    with pytest.raises(ValidationFailed) as refused:
        decline_listing(
            listing(), by_tenant_id=OWNER, owner_tenant_id=OWNER,
            reason=reason, account_ref=OWNER_ACCOUNT, now=_at(9),  # type: ignore[arg-type]
        )
    assert refused.value.field == "reason"
    with pytest.raises(ValidationFailed):
        suspend_listing(
            listing(_L.ADMITTED), by_tenant_id=OWNER, owner_tenant_id=OWNER,
            reason=reason, account_ref=OWNER_ACCOUNT, now=_at(9),  # type: ignore[arg-type]
        )


def test_a_listing_reason_of_another_enum_with_a_shared_value_is_refused() -> None:
    # GrantStatus.ENDED-style collision (lesson L3): the value 'declined' is a ListingStatus and a
    # GrantStatus, and must not pass as a ListingReason.
    with pytest.raises(ValidationFailed):
        suspend_listing(
            listing(_L.ADMITTED), by_tenant_id=OWNER, owner_tenant_id=OWNER,
            reason=GrantStatus.DECLINED, account_ref=OWNER_ACCOUNT, now=_at(9),  # type: ignore[arg-type]
        )


def test_the_source_tenant_withdraws_its_own_listing() -> None:
    withdrawn = withdraw_listing(listing(_L.ADMITTED), by_tenant_id=MEMBER, account_ref=MEMBER_ACCOUNT, now=_at(12))
    assert withdrawn.status is _L.WITHDRAWN
    assert withdrawn.decided_at == _at(12)


def test_the_owner_cannot_withdraw_a_members_listing() -> None:
    with pytest.raises(NotAllowed):
        withdraw_listing(listing(_L.ADMITTED), by_tenant_id=OWNER, account_ref=OWNER_ACCOUNT, now=_at(12))


def test_a_withdrawal_may_have_no_named_decider() -> None:
    withdrawn = withdraw_listing(listing(_L.PENDING), by_tenant_id=MEMBER, account_ref=None, now=_at(12))
    assert withdrawn.status is _L.WITHDRAWN
    assert withdrawn.decided_by_account_ref is None


# ---------------------------------------------------------------- 28. request


def test_a_member_requests_a_listing_for_its_own_tenant() -> None:
    requested = request_listing(
        [], row(), id="lst-9", network_id=NET, source_service_id="svc-ucr-west", now=_at(20)
    )
    assert requested.status is _L.PENDING
    assert requested.source_tenant_id == MEMBER
    assert requested.requested_at == _at(20)
    assert requested.decided_at is None


def test_an_inactive_membership_cannot_request() -> None:
    with pytest.raises(NotAllowed):
        request_listing(
            [], row(MembershipStatus.INVITED), id="lst-9", network_id=NET,
            source_service_id="svc-ucr-west", now=_at(20),
        )


def test_a_membership_of_another_network_cannot_request() -> None:
    with pytest.raises(NotAllowed):
        request_listing(
            [], row(network=OTHER_NET), id="lst-9", network_id=NET,
            source_service_id="svc-ucr-west", now=_at(20),
        )


@pytest.mark.parametrize("status", [_L.PENDING, _L.ADMITTED, _L.SUSPENDED])
def test_a_second_live_listing_of_one_service_is_a_conflict(status: ListingStatus) -> None:
    with pytest.raises(Conflict):
        request_listing(
            [listing(status)], row(), id="lst-9", network_id=NET,
            source_service_id="svc-ucr-west", now=_at(20),
        )


@pytest.mark.parametrize("status", [_L.DECLINED, _L.WITHDRAWN])
def test_a_new_request_is_allowed_after_a_declined_or_withdrawn_one(status: ListingStatus) -> None:
    again = request_listing(
        [listing(status)], row(), id="lst-9", network_id=NET,
        source_service_id="svc-ucr-west", now=_at(20),
    )
    assert again.id == "lst-9"
    assert again.status is _L.PENDING


def test_a_live_listing_of_another_service_does_not_block_a_request() -> None:
    other_service = listing(_L.ADMITTED, service="svc-other")
    fresh = request_listing(
        [other_service], row(), id="lst-9", network_id=NET,
        source_service_id="svc-ucr-west", now=_at(20),
    )
    assert fresh.status is _L.PENDING


# ---------------------------------------------------------------- 29. presentation


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (_L.ADMITTED, ListingPresentation.SHOWN),
        (_L.SUSPENDED, ListingPresentation.UNAVAILABLE),
        (_L.PENDING, ListingPresentation.HIDDEN),
        (_L.DECLINED, ListingPresentation.HIDDEN),
        (_L.WITHDRAWN, ListingPresentation.HIDDEN),
    ],
)
def test_listing_presentation_per_status(status: ListingStatus, expected: ListingPresentation) -> None:
    assert listing_presentation(status) is expected


def test_listing_presentation_refuses_a_foreign_status() -> None:
    with pytest.raises(ValidationFailed):
        listing_presentation(GrantStatus.APPROVED)  # type: ignore[arg-type]


# ---------------------------------------------------------------- 30. visible scopes


def test_a_listing_that_is_not_admitted_shows_no_scope() -> None:
    for status in (_L.PENDING, _L.DECLINED, _L.WITHDRAWN, _L.SUSPENDED):
        scopes = visible_scopes(listing(status), row(), [grant(), grant(scope=GrantScope.DIRECTORY, id="grt-2")], _at(70))
        assert scopes == frozenset()


def test_a_left_membership_shows_no_scope() -> None:
    scopes = visible_scopes(listing(_L.ADMITTED), row(MembershipStatus.LEFT), [grant()], _at(70))
    assert scopes == frozenset()


def test_an_admitted_member_with_no_effective_grant_shows_no_scope() -> None:
    assert visible_scopes(listing(_L.ADMITTED), row(), [], _at(70)) == frozenset()


def test_capacity_only_is_not_enough_for_the_board() -> None:
    grants = [grant(GrantStatus.APPROVED, scope=GrantScope.CAPACITY)]
    assert visible_scopes(listing(_L.ADMITTED), row(), grants, _at(70)) == frozenset({GrantScope.CAPACITY})
    assert shows_on_board(listing(_L.ADMITTED), row(), grants, _at(70)) is False


def test_directory_and_capacity_together_show_on_the_board() -> None:
    grants = [
        grant(GrantStatus.APPROVED, scope=GrantScope.CAPACITY, id="grt-1"),
        grant(GrantStatus.APPROVED, scope=GrantScope.DIRECTORY, id="grt-2"),
    ]
    assert shows_on_board(listing(_L.ADMITTED), row(), grants, _at(70)) is True


def test_criteria_is_optional_for_the_board() -> None:
    grants = [
        grant(GrantStatus.APPROVED, scope=GrantScope.CAPACITY, id="grt-1"),
        grant(GrantStatus.APPROVED, scope=GrantScope.DIRECTORY, id="grt-2"),
    ]
    assert shows_on_board(listing(_L.ADMITTED), row(), grants, _at(70)) is True


def test_another_members_grant_never_counts() -> None:
    grants = [grant(GrantStatus.APPROVED, grantor=OUTSIDER)]
    assert visible_scopes(listing(_L.ADMITTED), row(), grants, _at(70)) == frozenset()


def test_an_ended_grant_never_counts() -> None:
    grants = [grant(GrantStatus.ENDED, scope=GrantScope.CAPACITY)]
    assert visible_scopes(listing(_L.ADMITTED), row(), grants, _at(70)) == frozenset()


def test_a_suspended_listing_shows_no_scope_even_with_grants() -> None:
    grants = [grant(GrantStatus.APPROVED, scope=GrantScope.CAPACITY)]
    assert visible_scopes(listing(_L.SUSPENDED), row(), grants, _at(70)) == frozenset()


@settings(max_examples=300, deadline=None)
@given(
    st.sampled_from(list(ListingStatus)),
    st.sampled_from([MembershipStatus.ACTIVE, MembershipStatus.LEFT, MembershipStatus.INVITED]),
    st.lists(
        st.tuples(
            st.sampled_from(list(GrantStatus)),
            st.sampled_from(list(GrantScope)),
            st.sampled_from([MEMBER, OUTSIDER]),
            st.integers(min_value=0, max_value=100),
        ),
        max_size=6,
    ),
    st.integers(min_value=0, max_value=100),
)
def test_visible_scopes_is_a_subset_of_the_effective_scopes(
    status: ListingStatus,
    membership_status: MembershipStatus,
    raw_grants: list[tuple[GrantStatus, GrantScope, str, int]],
    minute: int,
) -> None:
    grants = []
    for index, (grant_status, scope, grantor, start) in enumerate(raw_grants):
        try:
            grants.append(
                replace(grant(grant_status, scope=scope, grantor=grantor, effective_from=start, id=f"grt-{index}"))
            )
        except ValidationFailed:
            continue
    membership_row = row(membership_status)
    scopes = visible_scopes(listing(status), membership_row, grants, _at(minute))
    from diucs.domain.rules.grant import is_effective

    effective = {
        g.scope
        for g in grants
        if g.grantor_tenant_id == MEMBER and is_effective(g, _at(minute))
    }
    assert scopes <= effective
    if status is not _L.ADMITTED or membership_status is not MembershipStatus.ACTIVE:
        assert scopes == frozenset()


# ---------------------------------------------------------------- 31. leaving


def test_leaving_withdraws_pending_admitted_and_suspended_listings_of_the_member() -> None:
    listings = [
        listing(_L.PENDING, id="lst-a", service="svc-1"),
        listing(_L.ADMITTED, id="lst-b", service="svc-2"),
        listing(_L.SUSPENDED, id="lst-c", service="svc-3"),
        listing(_L.DECLINED, id="lst-d", service="svc-4"),
        listing(_L.ADMITTED, id="lst-e", source=OUTSIDER, service="svc-5"),
    ]
    withdrawn = withdraw_for_leave(listings, row(MembershipStatus.LEFT), now=_at(31))
    assert [w.id for w in withdrawn] == ["lst-a", "lst-b", "lst-c"]
    assert all(w.status is _L.WITHDRAWN for w in withdrawn)
    assert all(w.decided_at == _at(31) for w in withdrawn)
    assert all(w.decided_by_account_ref is None for w in withdrawn)


def test_withdrawing_for_leave_needs_a_member_that_has_left() -> None:
    with pytest.raises(ValidationFailed):
        withdraw_for_leave([listing(_L.ADMITTED)], row(MembershipStatus.ACTIVE), now=_at(31))


# ---------------------------------------------------------------- 32. projection gate


def test_a_suspended_listing_does_not_project_even_with_an_effective_grant() -> None:
    assert may_project_listing(listing(_L.SUSPENDED), row(), grant(), _at(70)) is False


def test_an_admitted_listing_projects_with_an_effective_grant() -> None:
    assert may_project_listing(listing(_L.ADMITTED), row(), grant(), _at(70)) is True


def test_an_admitted_listing_does_not_project_without_an_effective_grant() -> None:
    assert may_project_listing(listing(_L.ADMITTED), row(), grant(), _at(5)) is False


def test_a_listing_of_another_tenant_does_not_project_through_this_member() -> None:
    assert may_project_listing(listing(_L.ADMITTED, source=OUTSIDER), row(), grant(), _at(70)) is False


def test_the_listing_key_is_network_source_and_service() -> None:
    first = listing(_L.PENDING, id="lst-1", service="svc-1")
    second = listing(_L.PENDING, id="lst-2", service="svc-1")
    assert (first.network_id, first.source_tenant_id, first.source_service_id) == (
        second.network_id, second.source_tenant_id, second.source_service_id,
    )


def test_a_listing_reason_is_a_code_from_the_fixed_list() -> None:
    assert [r.value for r in ListingReason] == [
        "outside-area", "outside-pilot", "duplicate-listing", "data-quality",
        "safety-concern", "agreement-breach", "other",
    ]


def test_the_listing_presentation_enum_has_the_three_values() -> None:
    assert [p.value for p in ListingPresentation] == ["shown", "unavailable", "hidden"]
