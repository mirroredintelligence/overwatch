"""Network records, identifiers, and membership rules (TEN-036; DEC-132, DEC-134, DEC-136).

Every expected value below is written out here, not imported from the module under test, so a
change to a table in network.py fails a test rather than passing with it.
"""

import ast
import itertools
import string
import sys
from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from diucs.application.tenancy import NETWORK_PREFIX, ScopeId, ScopeInvalid
from diucs.domain.errors import (
    Conflict,
    DomainError,
    InvalidTransition,
    NotAllowed,
    ValidationFailed,
)
from diucs.domain.model.network import (
    NETWORK_ID_PREFIX,
    Agreement,
    Approval,
    DirectorySource,
    Grant,
    GrantApprover,
    GrantEndReason,
    GrantPurpose,
    GrantScope,
    GrantStatus,
    Listing,
    ListingReason,
    ListingStatus,
    MembershipEndReason,
    MembershipRole,
    MembershipStatus,
    Network,
    NetworkMembership,
    NetworkStatus,
    accept_membership,
    activate_network,
    check_network_id,
    check_tenant_field,
    end_membership,
    invite_member,
    is_agreement_behind,
    owner_membership,
    transition_network,
    was_member_at,
)

T0 = datetime(2026, 4, 1, 9, 0, tzinfo=UTC)
AGREEMENT_V1 = Agreement("DSA-2026/14", 1)
AGREEMENT_V2 = Agreement("DSA-2026/14", 2)
OWNER = "tenant-a"
MEMBER = "tenant-b"
OUTSIDER = "tenant-c"
NET = "net-test"


def _at(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


def active_network(agreement: Agreement | None = AGREEMENT_V1) -> Network:
    return Network(
        id=NET,
        name="Sample network",
        owner_tenant_id=OWNER,
        status=NetworkStatus.ACTIVE,
        agreement=agreement,
        created_at=T0,
        closed_at=None,
    )


def membership(
    *,
    id: str = "mem-b",
    status: MembershipStatus = MembershipStatus.INVITED,
    role: MembershipRole = MembershipRole.MEMBER,
    invited_at: datetime = T0,
    joined_at: datetime | None = None,
    left_at: datetime | None = None,
    end_reason: MembershipEndReason | None = None,
    accepted_agreement: Agreement | None = None,
    member_tenant_id: str = MEMBER,
    network_id: str = NET,
) -> NetworkMembership:
    return NetworkMembership(
        id=id,
        network_id=network_id,
        member_tenant_id=member_tenant_id,
        role=role,
        status=status,
        invited_at=invited_at,
        joined_at=joined_at,
        left_at=left_at,
        end_reason=end_reason,
        accepted_agreement=accepted_agreement,
    )


def active_member(joined: int = 0, agreement: Agreement | None = AGREEMENT_V1) -> NetworkMembership:
    return membership(
        status=MembershipStatus.ACTIVE, joined_at=_at(joined), accepted_agreement=agreement
    )


# ---------------------------------------------------------------- 1. enum values


ENUM_VALUES = {
    GrantScope: ["capacity", "directory", "criteria"],
    GrantPurpose: ["network-capacity-view"],
    GrantStatus: [
        "proposed",
        "grantor-approved",
        "owner-approved",
        "approved",
        "declined",
        "ended",
        "lapsed",
        "superseded",
    ],
    GrantApprover: ["grantor", "owner"],
    GrantEndReason: ["ended", "lapsed", "superseded"],
    NetworkStatus: ["draft", "active", "suspended", "closed"],
    MembershipStatus: ["invited", "active", "left", "removed"],
    MembershipRole: ["owner", "member"],
    MembershipEndReason: ["left", "removed"],
    ListingStatus: ["pending", "admitted", "declined", "suspended", "withdrawn"],
    ListingReason: [
        "outside-area",
        "outside-pilot",
        "duplicate-listing",
        "data-quality",
        "safety-concern",
        "agreement-breach",
        "other",
    ],
    DirectorySource: ["manual", "directory-of-services"],
}


@pytest.mark.parametrize("enum_cls", list(ENUM_VALUES))
def test_enum_values_are_exactly_the_listed_ones(enum_cls: type) -> None:
    assert [member.value for member in enum_cls] == ENUM_VALUES[enum_cls]


def test_grant_purpose_has_one_member_and_directory_source_is_manual_today() -> None:
    assert [m.value for m in GrantPurpose] == ["network-capacity-view"]
    assert DirectorySource.MANUAL.value == "manual"


def test_network_prefix_is_the_kernel_prefix() -> None:
    assert NETWORK_ID_PREFIX == NETWORK_PREFIX == "net-"


# ---------------------------------------------------------------- 2. identifier kinds


def test_a_network_with_a_valid_id_builds() -> None:
    assert active_network().id == "net-test"


@pytest.mark.parametrize("bad_id", ["test", "net-", "net-Test", "net-" + "a" * 28, "tenant-a"])
def test_a_bad_network_id_is_refused_naming_the_id_field(bad_id: str) -> None:
    with pytest.raises(ValidationFailed) as refused:
        Network(
            id=bad_id,
            name="Sample network",
            owner_tenant_id=OWNER,
            status=NetworkStatus.DRAFT,
            agreement=None,
            created_at=T0,
            closed_at=None,
        )
    assert refused.value.field == "id"
    assert bad_id not in str(refused.value)


def test_a_network_id_as_owner_tenant_is_refused() -> None:
    with pytest.raises(ValidationFailed) as refused:
        Network(
            id=NET,
            name="Sample network",
            owner_tenant_id="net-test",
            status=NetworkStatus.DRAFT,
            agreement=None,
            created_at=T0,
            closed_at=None,
        )
    assert refused.value.field == "owner_tenant_id"


def test_a_network_id_as_member_tenant_is_refused() -> None:
    with pytest.raises(ValidationFailed) as refused:
        membership(member_tenant_id=NET)
    assert refused.value.field == "member_tenant_id"


def test_a_tenant_id_as_network_id_is_refused() -> None:
    with pytest.raises(ValidationFailed) as refused:
        membership(network_id=OWNER)
    assert refused.value.field == "network_id"


def test_a_network_id_as_source_tenant_is_refused() -> None:
    with pytest.raises(ValidationFailed) as refused:
        Listing(
            id="lst-1",
            network_id=NET,
            source_tenant_id="net-test",
            source_service_id="svc-1",
            status=ListingStatus.PENDING,
            requested_at=T0,
            decided_at=None,
            decided_by_account_ref=None,
            reason=None,
        )
    assert refused.value.field == "source_tenant_id"


NETWORK_ID_CORPUS = [
    "",
    "net-",
    "net-a",
    "net-ab",
    "net-abc",
    "net-a" * 6,
    "net-" + "a" * 26,
    "net-" + "a" * 27,
    "net-" + "a" * 28,
    "net-a-",
    "net--a",
    "net-A",
    "net-a_b",
    "net-a.b",
    "net-a:b",
    "net-a b",
    "net-a\n",
    "net",
    "nets-abc",
    "tenant-a",
    "default",
    "platform",
    "net-éé",
    "net-0",
    "net-00",
]


@pytest.mark.parametrize("text", NETWORK_ID_CORPUS)
def test_check_network_id_agrees_with_the_kernel_scope_id(text: str) -> None:
    try:
        ScopeId.network(text)
        kernel_accepts = True
    except ScopeInvalid:
        kernel_accepts = False
    try:
        check_network_id(text)
        ours_accepts = True
    except ValidationFailed:
        ours_accepts = False
    assert ours_accepts == kernel_accepts


@settings(max_examples=300, deadline=None)
@given(
    st.one_of(
        st.from_regex(r"net-[a-z0-9-]{0,34}", fullmatch=True),
        st.text(alphabet=string.ascii_lowercase + string.digits + "-_ .:A", max_size=36),
    )
)
def test_check_network_id_agrees_with_the_kernel_over_generated_text(text: str) -> None:
    try:
        ScopeId.network(text)
        kernel_accepts = True
    except ScopeInvalid:
        kernel_accepts = False
    try:
        check_network_id(text)
        ours_accepts = True
    except ValidationFailed:
        ours_accepts = False
    assert ours_accepts == kernel_accepts


def test_check_network_id_refuses_a_non_string_without_echoing_it() -> None:
    with pytest.raises(ValidationFailed) as refused:
        check_network_id(7)
    assert refused.value.field == "network_id"
    assert "7" not in refused.value.message


def test_check_tenant_field_names_the_given_field_not_tenant_id() -> None:
    assert check_tenant_field("tenant-a", "owner_tenant_id") == "tenant-a"
    with pytest.raises(ValidationFailed) as refused:
        check_tenant_field("net-test", "owner_tenant_id")
    assert refused.value.field == "owner_tenant_id"
    assert "net-test" not in str(refused.value)


# ---------------------------------------------------------------- 3. cross-enum collisions

COLLISIONS = [
    ("active", NetworkStatus.ACTIVE, MembershipStatus.ACTIVE),
    ("suspended", NetworkStatus.SUSPENDED, ListingStatus.SUSPENDED),
    ("declined", ListingStatus.DECLINED, GrantStatus.DECLINED),
    ("ended", GrantStatus.ENDED, GrantEndReason.ENDED),
    ("left", MembershipStatus.LEFT, MembershipEndReason.LEFT),
    ("removed", MembershipStatus.REMOVED, MembershipEndReason.REMOVED),
]


@pytest.mark.parametrize(("value", "native", "foreign"), COLLISIONS)
def test_the_collision_pairs_really_compare_equal(
    value: str, native: object, foreign: object
) -> None:
    # The hazard this section guards (lesson L3): a plain equality check would accept these.
    assert native == foreign
    assert native.value == foreign.value == value  # type: ignore[attr-defined]


def _refuses_a_foreign_member(enum_cls: type, call: object) -> None:
    """Every member of each collision pair that is not `enum_cls` must be refused by `call`."""
    for value, native, foreign in COLLISIONS:
        for member in (native, foreign):
            if type(member) is enum_cls:
                continue
            with pytest.raises(ValidationFailed) as refused:
                call(member)  # type: ignore[operator]
            assert value not in str(refused.value)


def test_a_foreign_member_as_a_membership_status_is_refused() -> None:
    _refuses_a_foreign_member(MembershipStatus, lambda m: membership(status=m))


def test_a_foreign_member_as_a_network_status_is_refused() -> None:
    _refuses_a_foreign_member(NetworkStatus, lambda m: transition_network(m, NetworkStatus.ACTIVE))


def test_a_foreign_member_as_an_end_reason_is_refused() -> None:
    _refuses_a_foreign_member(
        MembershipEndReason,
        lambda m: end_membership(active_network(), active_member(), reason=m, now=_at(5)),
    )


@pytest.mark.parametrize("plain", ["active", "left", "removed", "ended", "declined", "suspended"])
def test_a_plain_string_is_refused_where_an_enum_is_required(plain: str) -> None:
    with pytest.raises(ValidationFailed) as refused:
        membership(status=plain)  # type: ignore[arg-type]
    assert plain not in str(refused.value)
    with pytest.raises(ValidationFailed):
        transition_network(plain, NetworkStatus.ACTIVE)  # type: ignore[arg-type]


# ---------------------------------------------------------------- 4. Agreement


def test_agreement_has_exactly_the_reference_and_version_fields() -> None:
    assert tuple(f.name for f in fields(Agreement)) == ("reference", "version")


@pytest.mark.parametrize("reference", ["943 476 5919", "DT4 8XX", "", "a" * 65])
def test_agreement_refuses_a_bad_reference(reference: str) -> None:
    with pytest.raises(ValidationFailed) as refused:
        Agreement(reference, 1)
    assert refused.value.field == "reference"
    assert reference not in str(refused.value) or reference == ""


def test_agreement_refuses_version_zero() -> None:
    with pytest.raises(ValidationFailed) as refused:
        Agreement("DSA-2026/14", 0)
    assert refused.value.field == "version"


def test_agreement_builds_from_a_document_reference() -> None:
    assert Agreement("DSA-2026/14", 1).reference == "DSA-2026/14"


# ---------------------------------------------------------------- 5. membership invariants


@pytest.mark.parametrize(
    "kwargs",
    [
        {"status": MembershipStatus.INVITED, "joined_at": _at(1)},
        {"status": MembershipStatus.INVITED, "left_at": _at(1)},
        {"status": MembershipStatus.ACTIVE, "joined_at": None},
        {"status": MembershipStatus.ACTIVE, "joined_at": _at(1), "left_at": _at(2)},
        {
            "status": MembershipStatus.LEFT,
            "joined_at": _at(1),
            "left_at": _at(2),
            "end_reason": MembershipEndReason.REMOVED,
        },
        {
            "status": MembershipStatus.LEFT,
            "joined_at": _at(1),
            "end_reason": MembershipEndReason.LEFT,
        },
        {
            "status": MembershipStatus.LEFT,
            "joined_at": _at(3),
            "left_at": _at(2),
            "end_reason": MembershipEndReason.LEFT,
        },
        {
            "status": MembershipStatus.REMOVED,
            "joined_at": _at(1),
            "left_at": None,
            "end_reason": MembershipEndReason.REMOVED,
        },
        {"status": MembershipStatus.INVITED, "invited_at": datetime(2026, 4, 1, 9, 0)},
    ],
)
def test_a_membership_that_breaks_its_status_invariant_is_refused(
    kwargs: dict[str, object],
) -> None:
    with pytest.raises(ValidationFailed):
        membership(**kwargs)  # type: ignore[arg-type]


def test_a_valid_left_membership_builds() -> None:
    row = membership(
        status=MembershipStatus.LEFT,
        joined_at=_at(1),
        left_at=_at(9),
        end_reason=MembershipEndReason.LEFT,
    )
    assert row.left_at == _at(9)


# ---------------------------------------------------------------- 6. Network invariants


def test_an_active_network_without_an_agreement_is_refused() -> None:
    with pytest.raises(ValidationFailed) as refused:
        active_network(agreement=None)
    assert refused.value.field == "agreement"


def test_a_closed_network_without_a_closed_date_is_refused() -> None:
    with pytest.raises(ValidationFailed) as refused:
        Network(
            id=NET,
            name="Sample network",
            owner_tenant_id=OWNER,
            status=NetworkStatus.CLOSED,
            agreement=None,
            created_at=T0,
            closed_at=None,
        )
    assert refused.value.field == "closed_at"


@pytest.mark.parametrize("name", ["x" * 81, "Clinic SW1A 1AA"])
def test_a_network_name_that_is_too_long_or_has_a_postcode_is_refused(name: str) -> None:
    with pytest.raises(ValidationFailed) as refused:
        Network(
            id=NET,
            name=name,
            owner_tenant_id=OWNER,
            status=NetworkStatus.DRAFT,
            agreement=None,
            created_at=T0,
            closed_at=None,
        )
    assert refused.value.field == "name"


# ---------------------------------------------------------------- 7. network transitions

ALLOWED_NETWORK = {
    (NetworkStatus.DRAFT, NetworkStatus.ACTIVE),
    (NetworkStatus.ACTIVE, NetworkStatus.SUSPENDED),
    (NetworkStatus.SUSPENDED, NetworkStatus.ACTIVE),
    (NetworkStatus.ACTIVE, NetworkStatus.CLOSED),
    (NetworkStatus.SUSPENDED, NetworkStatus.CLOSED),
}


@pytest.mark.parametrize(
    ("current", "target"), list(itertools.product(list(NetworkStatus), repeat=2))
)
def test_every_network_transition_pair_is_allowed_or_refused(
    current: NetworkStatus, target: NetworkStatus
) -> None:
    if (current, target) in ALLOWED_NETWORK:
        assert transition_network(current, target) is target
    else:
        with pytest.raises(InvalidTransition):
            transition_network(current, target)


def test_nothing_leaves_closed() -> None:
    for target in NetworkStatus:
        with pytest.raises(InvalidTransition):
            transition_network(NetworkStatus.CLOSED, target)


def test_activate_network_needs_the_agreement_and_becomes_active() -> None:
    draft = Network(
        id=NET,
        name="Sample network",
        owner_tenant_id=OWNER,
        status=NetworkStatus.DRAFT,
        agreement=None,
        created_at=T0,
        closed_at=None,
    )
    activated = activate_network(draft, AGREEMENT_V1, _at(1))
    assert activated.status is NetworkStatus.ACTIVE
    assert activated.agreement == AGREEMENT_V1
    with pytest.raises(ValidationFailed):
        activate_network(draft, None, _at(1))  # type: ignore[arg-type]
    with pytest.raises(ValidationFailed):
        activate_network(draft, AGREEMENT_V1, datetime(2026, 4, 1, 9, 0))


# ---------------------------------------------------------------- 8. owner and invitations


def test_the_owner_membership_is_active_owner_with_the_networks_agreement() -> None:
    row = owner_membership(active_network(), "mem-owner", _at(0))
    assert row.status is MembershipStatus.ACTIVE
    assert row.role is MembershipRole.OWNER
    assert row.member_tenant_id == OWNER
    assert row.accepted_agreement == AGREEMENT_V1


def test_invite_refuses_the_owner_tenant_while_its_membership_is_active() -> None:
    network = active_network()
    owner_row = owner_membership(network, "mem-owner", _at(0))
    with pytest.raises(Conflict):
        invite_member(network, [owner_row], id="mem-x", tenant_id=OWNER, now=_at(1))


def test_invite_refuses_when_the_network_is_not_active() -> None:
    draft = Network(
        id=NET,
        name="Sample network",
        owner_tenant_id=OWNER,
        status=NetworkStatus.DRAFT,
        agreement=None,
        created_at=T0,
        closed_at=None,
    )
    with pytest.raises(Conflict):
        invite_member(draft, [], id="mem-b", tenant_id=MEMBER, now=_at(1))


@pytest.mark.parametrize("status", [MembershipStatus.INVITED, MembershipStatus.ACTIVE])
def test_invite_refuses_a_tenant_with_a_live_row(status: MembershipStatus) -> None:
    network = active_network()
    if status is MembershipStatus.INVITED:
        row = membership(status=MembershipStatus.INVITED)
    else:
        row = active_member()
    with pytest.raises(Conflict) as refused:
        invite_member(network, [row], id="mem-new", tenant_id=MEMBER, now=_at(2))
    assert MEMBER not in str(refused.value)


def test_invite_accepts_a_tenant_whose_only_row_is_left_and_leaves_that_row_alone() -> None:
    network = active_network()
    closed_row = membership(
        id="mem-old",
        status=MembershipStatus.LEFT,
        joined_at=_at(1),
        left_at=_at(5),
        end_reason=MembershipEndReason.LEFT,
    )
    before = closed_row
    fresh = invite_member(network, [closed_row], id="mem-new", tenant_id=MEMBER, now=_at(9))
    assert fresh.id == "mem-new"
    assert fresh.status is MembershipStatus.INVITED
    assert fresh.joined_at is None
    assert closed_row == before
    assert closed_row.left_at == _at(5)


def test_invite_refuses_a_membership_row_from_another_network() -> None:
    other = membership(network_id="net-other", status=MembershipStatus.INVITED)
    with pytest.raises(ValidationFailed):
        invite_member(active_network(), [other], id="mem-new", tenant_id=OUTSIDER, now=_at(1))


# ---------------------------------------------------------------- 9. accepting


def test_accepting_sets_joined_at_to_now() -> None:
    network = active_network()
    invited = membership()
    accepted = accept_membership(
        network, invited, agreement=AGREEMENT_V1, account_ref="acct-b-0001", now=_at(3)
    )
    assert accepted.status is MembershipStatus.ACTIVE
    assert accepted.joined_at == _at(3)
    assert accepted.accepted_agreement == AGREEMENT_V1


def test_accepting_a_different_agreement_version_is_a_conflict() -> None:
    with pytest.raises(Conflict):
        accept_membership(
            active_network(AGREEMENT_V2),
            membership(),
            agreement=AGREEMENT_V1,
            account_ref="acct-b-0001",
            now=_at(3),
        )


def test_accepting_with_a_naive_time_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        accept_membership(
            active_network(),
            membership(),
            agreement=AGREEMENT_V1,
            account_ref="acct-b-0001",
            now=datetime(2026, 4, 1, 9, 0),
        )


# ---------------------------------------------------------------- 10. leaving and history


def test_leaving_keeps_joined_at_and_sets_the_leave_date() -> None:
    left = end_membership(
        active_network(), active_member(joined=1), reason=MembershipEndReason.LEFT, now=_at(9)
    )
    assert left.status is MembershipStatus.LEFT
    assert left.end_reason is MembershipEndReason.LEFT
    assert left.joined_at == _at(1)
    assert left.left_at == _at(9)


def test_history_is_marked_with_the_leave_date() -> None:
    left = end_membership(
        active_network(), active_member(joined=1), reason=MembershipEndReason.LEFT, now=_at(9)
    )
    assert was_member_at(left, _at(9) - timedelta(microseconds=1)) is True
    assert was_member_at(left, _at(9)) is False
    assert was_member_at(left, _at(1) - timedelta(microseconds=1)) is False
    assert was_member_at(left, _at(1)) is True


def test_was_member_at_compares_instants_across_the_london_clock_change() -> None:
    # Lesson L4: aware datetimes that share one zone object compare wall-clock time, and on
    # 2026-10-25 London repeats 01:00 to 02:00. The checks are made on instants: 01:00 UTC is
    # inside the membership even though its wall clock (01:00) is before the joined wall clock.
    london = ZoneInfo("Europe/London")
    joined = datetime(2026, 10, 25, 0, 30, tzinfo=UTC).astimezone(london)
    left_at = datetime(2026, 10, 25, 1, 30, tzinfo=UTC).astimezone(london)
    row = membership(
        status=MembershipStatus.LEFT,
        joined_at=joined,
        left_at=left_at,
        end_reason=MembershipEndReason.LEFT,
    )
    inside = datetime(2026, 10, 25, 1, 0, tzinfo=UTC).astimezone(london)
    just_before_leaving = datetime(2026, 10, 25, 1, 29, 59, 999999, tzinfo=UTC).astimezone(london)
    assert was_member_at(row, inside) is True
    assert was_member_at(row, just_before_leaving) is True
    assert was_member_at(row, left_at) is False


def test_the_owner_cannot_leave_its_own_network() -> None:
    network = active_network()
    with pytest.raises(NotAllowed):
        end_membership(
            network,
            owner_membership(network, "mem-owner", _at(0)),
            reason=MembershipEndReason.LEFT,
            now=_at(5),
        )


def test_ending_a_left_membership_with_the_same_reason_returns_it_unchanged() -> None:
    network = active_network()
    left = end_membership(
        network, active_member(joined=1), reason=MembershipEndReason.LEFT, now=_at(9)
    )
    assert end_membership(network, left, reason=MembershipEndReason.LEFT, now=_at(20)) == left


def test_ending_a_left_membership_with_a_different_reason_is_refused() -> None:
    network = active_network()
    left = end_membership(
        network, active_member(joined=1), reason=MembershipEndReason.LEFT, now=_at(9)
    )
    with pytest.raises(InvalidTransition):
        end_membership(network, left, reason=MembershipEndReason.REMOVED, now=_at(20))


def test_an_invited_tenant_can_be_removed_but_not_marked_as_left() -> None:
    network = active_network()
    removed = end_membership(network, membership(), reason=MembershipEndReason.REMOVED, now=_at(4))
    assert removed.status is MembershipStatus.REMOVED
    assert removed.joined_at is None
    assert removed.left_at == _at(4)
    with pytest.raises(InvalidTransition):
        end_membership(network, membership(), reason=MembershipEndReason.LEFT, now=_at(4))


def test_an_active_member_can_be_removed_and_keeps_its_join_date() -> None:
    removed = end_membership(
        active_network(), active_member(joined=2), reason=MembershipEndReason.REMOVED, now=_at(8)
    )
    assert removed.status is MembershipStatus.REMOVED
    assert removed.joined_at == _at(2)
    assert removed.end_reason is MembershipEndReason.REMOVED


def test_ending_a_membership_of_another_network_is_refused() -> None:
    other = membership(network_id="net-other", status=MembershipStatus.ACTIVE, joined_at=_at(1))
    with pytest.raises(ValidationFailed):
        end_membership(active_network(), other, reason=MembershipEndReason.LEFT, now=_at(5))


# ---------------------------------------------------------------- 11. agreement behind


@pytest.mark.parametrize(
    ("network_agreement", "accepted", "behind"),
    [
        (AGREEMENT_V2, None, True),
        (AGREEMENT_V2, Agreement("DSA-2026/14", 1), True),
        (AGREEMENT_V2, AGREEMENT_V2, False),
        (AGREEMENT_V1, Agreement("DSA-2026/15", 2), False),
        (None, None, False),
    ],
)
def test_is_agreement_behind(
    network_agreement: Agreement | None, accepted: Agreement | None, behind: bool
) -> None:
    network = Network(
        id=NET,
        name="Sample network",
        owner_tenant_id=OWNER,
        status=NetworkStatus.DRAFT if network_agreement is None else NetworkStatus.ACTIVE,
        agreement=network_agreement,
        created_at=T0,
        closed_at=None,
    )
    row = membership(status=MembershipStatus.ACTIVE, joined_at=_at(1), accepted_agreement=accepted)
    assert is_agreement_behind(network, row) is behind


# ---------------------------------------------------------------- 12. validators and frozenness


def test_check_tenant_field_accepts_a_trailing_hyphen_as_tenant_006_does() -> None:
    assert check_tenant_field("tenant-a-", "tenant_id") == "tenant-a-"


@pytest.mark.parametrize("value", ["", "Tenant-A", "net-test", "a", 3, None])
def test_check_tenant_field_refuses_what_the_tenant_format_refuses(value: object) -> None:
    with pytest.raises(ValidationFailed) as refused:
        check_tenant_field(value, "tenant_id")
    assert refused.value.field == "tenant_id"
    assert "net-test" not in str(refused.value)


def test_check_tenant_field_accepts_a_tenant() -> None:
    assert check_tenant_field("tenant-a", "tenant_id") == "tenant-a"


@pytest.mark.parametrize("value", ["", "NET-test", "tenant-a", "net-test ", 5])
def test_check_network_id_refuses_what_the_network_format_refuses(value: object) -> None:
    with pytest.raises(ValidationFailed) as refused:
        check_network_id(value)
    assert refused.value.field == "network_id"


def test_check_network_id_accepts_a_network() -> None:
    assert check_network_id("net-test") == "net-test"


@pytest.mark.parametrize(
    "record",
    [
        Agreement("DSA-2026/14", 1),
        active_network(),
        active_member(),
        Approval("acct-a-0001", OWNER, _at(1)),
    ],
)
def test_records_are_frozen(record: object) -> None:
    name = fields(record)[0].name  # type: ignore[arg-type]
    with pytest.raises(FrozenInstanceError):
        setattr(record, name, "changed")


# ---------------------------------------------------------------- purity and imports

DOMAIN_RULE_FILES = [
    Path(__file__).resolve().parents[4] / "src/diucs/domain/model/network.py",
    Path(__file__).resolve().parents[4] / "src/diucs/domain/rules/grant.py",
    Path(__file__).resolve().parents[4] / "src/diucs/domain/rules/listing.py",
]
FORBIDDEN_IN_SOURCE = ("datetime.now", "utcnow", "time.time", "os.environ")


@pytest.mark.parametrize("path", DOMAIN_RULE_FILES, ids=lambda p: p.name)
def test_no_module_reads_the_clock_or_the_environment(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for needle in FORBIDDEN_IN_SOURCE:
        assert needle not in text, f"{path.name} contains {needle}"


@pytest.mark.parametrize("path", DOMAIN_RULE_FILES, ids=lambda p: p.name)
def test_imports_are_standard_library_or_domain_only(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    allowed_roots = set(sys.stdlib_module_names) | {"diucs", "fhir"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                continue
            names = [node.module or ""]
        else:
            continue
        for name in names:
            root = name.split(".")[0]
            assert root in allowed_roots, f"{path.name} imports {name}"
            if root == "diucs":
                assert name == "diucs.domain" or name.startswith("diucs.domain."), name


def test_a_grant_scope_value_outside_the_list_does_not_exist() -> None:
    assert {m.value for m in GrantScope} == {"capacity", "directory", "criteria"}


def test_a_listing_reason_is_a_code_and_never_free_text() -> None:
    assert all(member.value == member.value.lower() for member in ListingReason)


@pytest.mark.parametrize("error", [Conflict, NotAllowed, InvalidTransition])
def test_the_refusals_are_domain_errors(error: type[DomainError]) -> None:
    assert issubclass(error, DomainError)


# A Hypothesis guard on the membership span: a span is valid only when left_at is not before
# joined_at, whatever the offsets are.
@settings(max_examples=200, deadline=None)
@given(st.integers(min_value=0, max_value=5000), st.integers(min_value=-5000, max_value=5000))
def test_left_at_must_not_be_before_joined_at(joined: int, delta: int) -> None:
    left = _at(joined + delta)
    if delta < 0:
        with pytest.raises(ValidationFailed):
            membership(
                status=MembershipStatus.LEFT,
                joined_at=_at(joined),
                left_at=left,
                end_reason=MembershipEndReason.LEFT,
            )
    else:
        row = membership(
            status=MembershipStatus.LEFT,
            joined_at=_at(joined),
            left_at=left,
            end_reason=MembershipEndReason.LEFT,
        )
        assert row.left_at == left


# ---------------------------------------------------------------- coverage of every refusal


def test_a_membership_id_with_a_space_is_refused() -> None:
    with pytest.raises(ValidationFailed) as refused:
        membership(id="mem b")
    assert refused.value.field == "id"


def test_an_approval_with_a_short_account_reference_is_refused() -> None:
    with pytest.raises(ValidationFailed) as refused:
        Approval("short", OWNER, _at(1))
    assert refused.value.field == "account_ref"


def test_an_approval_by_a_network_id_is_refused_as_a_tenant() -> None:
    with pytest.raises(ValidationFailed) as refused:
        Approval("acct-owner-0001", NET, _at(1))
    assert refused.value.field == "tenant_id"


def test_a_closed_at_on_a_network_that_is_not_closed_is_refused() -> None:
    with pytest.raises(ValidationFailed) as refused:
        Network(
            id=NET,
            name="Sample network",
            owner_tenant_id=OWNER,
            status=NetworkStatus.DRAFT,
            agreement=None,
            created_at=T0,
            closed_at=_at(3),
        )
    assert refused.value.field == "closed_at"


def test_a_network_that_is_not_an_agreement_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        Network(
            id=NET,
            name="Sample network",
            owner_tenant_id=OWNER,
            status=NetworkStatus.DRAFT,
            agreement="DSA-2026/14",  # type: ignore[arg-type]
            created_at=T0,
            closed_at=None,
        )


def test_an_invitation_that_already_names_an_agreement_is_refused() -> None:
    with pytest.raises(ValidationFailed) as refused:
        membership(status=MembershipStatus.INVITED, accepted_agreement=AGREEMENT_V1)
    assert refused.value.field == "status"


def test_a_removed_membership_that_never_joined_builds() -> None:
    row = membership(
        status=MembershipStatus.REMOVED, left_at=_at(2), end_reason=MembershipEndReason.REMOVED
    )
    assert row.joined_at is None


def test_a_removed_membership_needs_its_end_reason_and_leave_date() -> None:
    with pytest.raises(ValidationFailed):
        membership(
            status=MembershipStatus.REMOVED, left_at=_at(2), end_reason=MembershipEndReason.LEFT
        )


def _grant_kwargs(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "id": "grt-1",
        "network_id": NET,
        "grantor_tenant_id": MEMBER,
        "scope": GrantScope.CAPACITY,
        "purpose": GrantPurpose.NETWORK_CAPACITY_VIEW,
        "version": 1,
        "status": GrantStatus.PROPOSED,
        "effective_from": _at(10),
        "effective_to": None,
        "agreement": AGREEMENT_V1,
        "allowlist_version": 1,
        "proposed_by_account_ref": "acct-member-0001",
        "proposed_at": T0,
        "grantor_approval": None,
        "owner_approval": None,
        "ended_at": None,
        "ended_by_account_ref": None,
        "supersedes_id": None,
    }
    values.update(overrides)
    return values


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"version": 0}, "version"),
        ({"allowlist_version": 0}, "allowlist_version"),
        ({"scope": "capacity"}, "scope"),
        ({"purpose": "network-capacity-view"}, "purpose"),
        ({"status": "proposed"}, "status"),
        ({"effective_from": datetime(2026, 4, 1, 9, 10)}, "effective_from"),
        ({"effective_to": _at(5)}, "effective_to"),
        ({"effective_to": datetime(2026, 4, 1, 9, 30)}, "effective_to"),
        ({"proposed_by_account_ref": "x"}, "proposed_by_account_ref"),
        ({"proposed_at": datetime(2026, 4, 1, 9, 0)}, "proposed_at"),
        ({"agreement": "DSA-2026/14"}, "agreement"),
        ({"ended_by_account_ref": "acct-owner-0001"}, "status"),
        (
            {
                "ended_at": _at(20),
                "status": GrantStatus.LAPSED,
                "ended_by_account_ref": "acct-owner-0001",
            },
            "status",
        ),
        ({"ended_at": _at(20), "status": GrantStatus.ENDED}, "status"),
        ({"status": GrantStatus.GRANTOR_APPROVED}, "status"),
        ({"status": GrantStatus.OWNER_APPROVED}, "status"),
        ({"status": GrantStatus.APPROVED}, "status"),
        ({"status": GrantStatus.LAPSED}, "status"),
        ({"supersedes_id": "grt-1"}, "supersedes_id"),
        ({"supersedes_id": "bad id"}, "supersedes_id"),
        ({"id": "bad id"}, "id"),
        ({"network_id": "tenant-a"}, "network_id"),
        ({"grantor_tenant_id": "net-test"}, "grantor_tenant_id"),
    ],
)
def test_a_grant_that_breaks_a_field_rule_or_its_status_is_refused(
    overrides: dict[str, object], field: str
) -> None:
    with pytest.raises(ValidationFailed) as refused:
        Grant(**_grant_kwargs(**overrides))  # type: ignore[arg-type]
    assert refused.value.field == field


def test_a_grantor_approval_by_another_tenant_is_refused() -> None:
    approval = Approval("acct-member-0001", OUTSIDER, _at(2))
    with pytest.raises(ValidationFailed) as refused:
        Grant(**_grant_kwargs(status=GrantStatus.GRANTOR_APPROVED, grantor_approval=approval))  # type: ignore[arg-type]
    assert refused.value.field == "grantor_approval"


def test_a_grant_that_is_not_a_grant_approval_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        Grant(**_grant_kwargs(grantor_approval="acct-member-0001"))  # type: ignore[arg-type]


def test_a_valid_ended_and_declined_grant_builds() -> None:
    declined = Grant(**_grant_kwargs(status=GrantStatus.DECLINED, ended_at=_at(20)))  # type: ignore[arg-type]
    ended = Grant(
        **_grant_kwargs(  # type: ignore[arg-type]
            status=GrantStatus.ENDED, ended_at=_at(20), ended_by_account_ref="acct-member-0001"
        )
    )
    assert declined.ended_by_account_ref is None
    assert ended.ended_by_account_ref == "acct-member-0001"


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"status": ListingStatus.PENDING, "decided_at": _at(3)}, "status"),
        ({"status": ListingStatus.PENDING, "reason": ListingReason.OTHER}, "status"),
        ({"status": ListingStatus.ADMITTED, "decided_at": _at(3)}, "status"),
        (
            {
                "status": ListingStatus.ADMITTED,
                "decided_at": _at(3),
                "decided_by_account_ref": "acct-owner-0001",
                "reason": ListingReason.OTHER,
            },
            "status",
        ),
        (
            {
                "status": ListingStatus.DECLINED,
                "decided_at": _at(3),
                "decided_by_account_ref": "acct-owner-0001",
            },
            "status",
        ),
        (
            {
                "status": ListingStatus.SUSPENDED,
                "decided_at": _at(3),
                "reason": ListingReason.OTHER,
            },
            "status",
        ),
        ({"status": ListingStatus.WITHDRAWN, "reason": ListingReason.OTHER}, "status"),
        ({"status": ListingStatus.WITHDRAWN}, "status"),
        ({"status": "pending"}, "status"),
        ({"reason": "other"}, "reason"),
        ({"requested_at": datetime(2026, 4, 1, 9, 0)}, "requested_at"),
        (
            {"decided_at": datetime(2026, 4, 1, 9, 0), "status": ListingStatus.WITHDRAWN},
            "decided_at",
        ),
        ({"decided_by_account_ref": "x"}, "decided_by_account_ref"),
        ({"source_service_id": "bad service"}, "source_service_id"),
        ({"source_tenant_id": NET}, "source_tenant_id"),
        ({"network_id": OWNER}, "network_id"),
        ({"id": "bad id"}, "id"),
    ],
)
def test_a_listing_that_breaks_its_status_or_field_rule_is_refused(
    overrides: dict[str, object], field: str
) -> None:
    values: dict[str, object] = {
        "id": "lst-1",
        "network_id": NET,
        "source_tenant_id": MEMBER,
        "source_service_id": "svc-1",
        "status": ListingStatus.PENDING,
        "requested_at": T0,
        "decided_at": None,
        "decided_by_account_ref": None,
        "reason": None,
    }
    values.update(overrides)
    with pytest.raises(ValidationFailed) as refused:
        Listing(**values)  # type: ignore[arg-type]
    assert refused.value.field == field


def test_a_withdrawn_listing_may_name_no_decider() -> None:
    withdrawn = Listing(
        id="lst-1",
        network_id=NET,
        source_tenant_id=MEMBER,
        source_service_id="svc-1",
        status=ListingStatus.WITHDRAWN,
        requested_at=T0,
        decided_at=_at(4),
        decided_by_account_ref=None,
        reason=None,
    )
    assert withdrawn.decided_by_account_ref is None


def test_accepting_an_invitation_of_another_network_is_refused() -> None:
    other = membership(network_id="net-other", status=MembershipStatus.INVITED)
    with pytest.raises(ValidationFailed):
        accept_membership(
            active_network(), other, agreement=AGREEMENT_V1, account_ref="acct-b-0001", now=_at(3)
        )


def test_accepting_a_membership_that_is_not_an_invitation_is_refused() -> None:
    with pytest.raises(InvalidTransition):
        accept_membership(
            active_network(),
            active_member(),
            agreement=AGREEMENT_V1,
            account_ref="acct-b-0001",
            now=_at(3),
        )


def test_accepting_on_a_suspended_network_is_a_conflict() -> None:
    suspended = Network(
        id=NET,
        name="Sample network",
        owner_tenant_id=OWNER,
        status=NetworkStatus.SUSPENDED,
        agreement=AGREEMENT_V1,
        created_at=T0,
        closed_at=None,
    )
    with pytest.raises(Conflict):
        accept_membership(
            suspended, membership(), agreement=AGREEMENT_V1, account_ref="acct-b-0001", now=_at(3)
        )


def test_an_account_reference_that_is_too_short_is_refused_when_accepting() -> None:
    with pytest.raises(ValidationFailed) as refused:
        accept_membership(
            active_network(), membership(), agreement=AGREEMENT_V1, account_ref="short", now=_at(3)
        )
    assert refused.value.field == "account_ref"


def test_was_member_at_is_false_for_an_invitation_and_true_while_active() -> None:
    assert was_member_at(membership(), _at(100)) is False
    assert was_member_at(active_member(joined=1), _at(100)) is True
    assert was_member_at(active_member(joined=1), _at(0)) is False


def test_an_owner_membership_is_refused_a_leave_by_its_own_tenant_even_when_active() -> None:
    network = active_network()
    with pytest.raises(NotAllowed):
        end_membership(
            network,
            owner_membership(network, "mem-owner", _at(0)),
            reason=MembershipEndReason.REMOVED,
            now=_at(5),
        )


def test_ending_a_membership_of_a_member_with_a_non_membership_record_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        end_membership(
            active_network(),
            "not a membership",  # type: ignore[arg-type]
            reason=MembershipEndReason.LEFT,
            now=_at(5),
        )


def test_inviting_with_an_existing_row_that_is_not_a_membership_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        invite_member(
            active_network(),
            ["not a membership"],  # type: ignore[list-item]
            id="mem-new",
            tenant_id=MEMBER,
            now=_at(2),
        )


def test_owner_membership_needs_a_valid_id_and_an_aware_time() -> None:
    with pytest.raises(ValidationFailed):
        owner_membership(active_network(), "bad id", _at(0))
    with pytest.raises(ValidationFailed):
        owner_membership(active_network(), "mem-owner", datetime(2026, 4, 1, 9, 0))


def test_invite_refuses_a_bad_tenant_or_naive_time_before_anything_else() -> None:
    with pytest.raises(ValidationFailed):
        invite_member(active_network(), [], id="mem-new", tenant_id="net-test", now=_at(2))
    with pytest.raises(ValidationFailed):
        invite_member(
            active_network(), [], id="mem-new", tenant_id=MEMBER, now=datetime(2026, 4, 1)
        )


def test_activating_a_network_needs_a_valid_time_and_a_transition() -> None:
    draft = Network(
        id=NET,
        name="Sample network",
        owner_tenant_id=OWNER,
        status=NetworkStatus.DRAFT,
        agreement=None,
        created_at=T0,
        closed_at=None,
    )
    closed = Network(
        id=NET,
        name="Sample network",
        owner_tenant_id=OWNER,
        status=NetworkStatus.CLOSED,
        agreement=None,
        created_at=T0,
        closed_at=_at(1),
    )
    with pytest.raises(InvalidTransition):
        activate_network(closed, AGREEMENT_V1, _at(2))
    assert activate_network(draft, AGREEMENT_V1, _at(2)).status is NetworkStatus.ACTIVE


def test_check_tenant_field_and_network_id_refuse_a_non_string_by_type() -> None:
    with pytest.raises(ValidationFailed):
        check_tenant_field(None, "owner_tenant_id")
    with pytest.raises(ValidationFailed):
        check_network_id(None)


def test_an_agreement_reference_that_names_a_person_is_refused() -> None:
    with pytest.raises(ValidationFailed) as refused:
        Agreement("Dr Smith 2026", 1)
    assert refused.value.field == "reference"


def test_a_network_name_must_be_text() -> None:
    with pytest.raises(ValidationFailed):
        Network(
            id=NET,
            name=12,
            owner_tenant_id=OWNER,
            status=NetworkStatus.DRAFT,  # type: ignore[arg-type]
            agreement=None,
            created_at=T0,
            closed_at=None,
        )
