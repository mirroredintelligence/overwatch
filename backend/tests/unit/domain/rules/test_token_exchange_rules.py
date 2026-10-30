"""The pure rules of the token exchange (TEN-043, DEC-523 to DEC-526, DEC-134 item 2, DEC-136).

A staff role comes from the tenant's own role mapping and from nothing the token says: the groups
the verified identity holds are looked up in the ACTIVE mappings of the tenant, and the highest
role among them wins. A directory counts as the tenant's only when its binding is VERIFIED. An
operator role comes from the operator directory's own app roles. Whether the back end may issue a
token for a tenant follows the one edge rule (an active tenant; a read-only suspended tenant for its
administrator only), so the issue and the edge never disagree. A person's identity at a tenant is
derived from the directory and the object id with a platform key: the same object id in two
directories is two people, and the same person in two tenants is two subjects.
"""

import re
from datetime import UTC, datetime, timedelta

import pytest

from diucs.domain.codes import Role
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.network import ACCOUNT_REF_PATTERN
from diucs.domain.model.tenant import SuspendMode, TenantStatus
from diucs.domain.model.tenant_records import (
    BindingStatus,
    EntraBinding,
    MappingStatus,
    RoleMapping,
)
from diucs.domain.rules.token_exchange import (
    OPERATOR_ROLE_CLAIMS,
    OPERATOR_TOKEN_LIFETIME,
    STAFF_ROLE_PRIORITY,
    STAFF_TOKEN_LIFETIME,
    WALL_TOKEN_LIFETIME,
    account_ref,
    directory_is_bound,
    expiry,
    may_issue,
    operator_role,
    staff_role,
    staff_subject,
)
from tests.support.tenant_samples import make_tenant

KEY = b"synthetic-account-ref-key-for-the-exchange-rules-1"
OTHER_KEY = b"another-synthetic-account-ref-key-for-the-rules-2"
D1 = "11111111-1111-4111-8111-111111111111"
D2 = "22222222-2222-4222-8222-222222222222"
OID = "33333333-3333-4333-8333-333333333333"
G_LEAD = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
G_ADVISOR = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
G_EXEC = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
G_OTHER = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
NOW = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)


def mapping(group: str, role: Role, status: MappingStatus = MappingStatus.ACTIVE) -> RoleMapping:
    return RoleMapping(group_object_id=group, role=role, status=status)


def forced(group: str, role: Role) -> RoleMapping:
    """A mapping that holds a role the record refuses, as a damaged store might return it."""
    made = mapping(group, Role.ADVISOR)
    object.__setattr__(made, "role", role)
    return made


def verified(directory: str) -> EntraBinding:
    return EntraBinding(
        directory_id=directory,
        status=BindingStatus.VERIFIED,
        verified_at=NOW,
        verified_by_ref="operator-ref-1",
    )


def binding(directory: str, status: BindingStatus) -> EntraBinding:
    if status is BindingStatus.VERIFIED:
        return verified(directory)
    return EntraBinding(directory_id=directory, status=status)


# ----------------------------------------------------------------------- the staff role


def test_a_held_group_gives_the_role_its_mapping_names() -> None:
    assert staff_role([mapping(G_LEAD, Role.LEAD)], [G_LEAD]) is Role.LEAD


def test_no_mapping_and_no_group_give_no_role() -> None:
    assert staff_role([], [G_LEAD]) is None
    assert staff_role([mapping(G_LEAD, Role.LEAD)], []) is None
    assert staff_role([mapping(G_LEAD, Role.LEAD)], [G_OTHER]) is None


def test_a_retired_mapping_gives_nothing() -> None:
    assert staff_role([mapping(G_LEAD, Role.LEAD, MappingStatus.RETIRED)], [G_LEAD]) is None


def test_the_highest_role_among_the_held_groups_wins() -> None:
    mappings = [
        mapping(G_EXEC, Role.EXEC),
        mapping(G_ADVISOR, Role.ADVISOR),
        mapping(G_LEAD, Role.LEAD),
    ]

    assert staff_role(mappings, [G_EXEC, G_ADVISOR, G_LEAD]) is Role.LEAD
    assert staff_role(mappings, [G_EXEC, G_ADVISOR]) is Role.ADVISOR
    assert staff_role(mappings, [G_EXEC]) is Role.EXEC


def test_the_order_of_the_mappings_and_of_the_groups_changes_nothing() -> None:
    mappings = [mapping(G_LEAD, Role.LEAD), mapping(G_ADVISOR, Role.ADVISOR)]

    assert staff_role(mappings, [G_ADVISOR, G_LEAD]) is staff_role(
        mappings[::-1], [G_LEAD, G_ADVISOR]
    )


def test_a_group_is_matched_whatever_its_case() -> None:
    assert staff_role([mapping(G_LEAD, Role.LEAD)], [G_LEAD.upper()]) is Role.LEAD


@pytest.mark.parametrize(
    "role",
    [Role.SUPPORT, Role.PLATFORM_OPERATOR, Role.WALL, Role.REPORTER, Role.ANONYMOUS_LINK],
)
def test_a_mapping_that_holds_a_role_that_is_not_a_staff_role_is_ignored(role: Role) -> None:
    # The record refuses these, so only a damaged store can return one; a platform role from a
    # customer's directory is the hole W09 had (DEC-134 item 5).
    assert staff_role([forced(G_LEAD, role)], [G_LEAD]) is None


def test_a_mapping_that_is_not_a_mapping_is_ignored() -> None:
    assert staff_role([object()], [G_LEAD]) is None  # type: ignore[list-item]


def test_the_staff_priority_lists_the_administration_roles_first_and_no_platform_role() -> None:
    assert STAFF_ROLE_PRIORITY[:2] == (Role.TENANT_ADMIN, Role.NETWORK_ADMIN)
    assert Role.SUPPORT not in STAFF_ROLE_PRIORITY
    assert Role.PLATFORM_OPERATOR not in STAFF_ROLE_PRIORITY
    assert Role.WALL not in STAFF_ROLE_PRIORITY
    assert len(set(STAFF_ROLE_PRIORITY)) == len(STAFF_ROLE_PRIORITY)


# ----------------------------------------------------------------------- the operator role


def test_the_operator_claims_name_two_platform_roles() -> None:
    assert dict(OPERATOR_ROLE_CLAIMS) == {
        "DIUCS.PlatformOperator": Role.PLATFORM_OPERATOR,
        "DIUCS.Support": Role.SUPPORT,
    }


def test_an_operator_role_comes_from_the_operators_own_app_roles() -> None:
    assert operator_role(["DIUCS.Support"]) is Role.SUPPORT
    assert operator_role(["DIUCS.PlatformOperator"]) is Role.PLATFORM_OPERATOR


def test_a_person_with_both_operator_roles_is_the_platform_operator_who_has_no_data_access() -> (
    None
):
    assert operator_role(["DIUCS.Support", "DIUCS.PlatformOperator"]) is Role.PLATFORM_OPERATOR


@pytest.mark.parametrize(
    "claims",
    [
        [],
        ["DIUCS.Advisor"],
        ["DIUCS.Lead"],
        ["support"],
        ["diucs.support"],
        ["DIUCS.Support "],
        [""],
    ],
)
def test_an_app_role_that_is_not_an_operator_claim_gives_no_role(claims: list[str]) -> None:
    assert operator_role(claims) is None


def test_an_operator_claim_that_is_not_text_is_ignored() -> None:
    assert operator_role([7, None, ("DIUCS.Support",)]) is None  # type: ignore[list-item]


# ----------------------------------------------------------------------- the bound directory


def test_a_verified_binding_binds_its_directory() -> None:
    assert directory_is_bound([verified(D1)], D1) is True


@pytest.mark.parametrize("status", [BindingStatus.PENDING, BindingStatus.REVOKED])
def test_a_binding_that_is_not_verified_binds_nothing(status: BindingStatus) -> None:
    assert directory_is_bound([binding(D1, status)], D1) is False


def test_a_binding_of_another_directory_binds_nothing_here() -> None:
    assert directory_is_bound([verified(D2)], D1) is False
    assert directory_is_bound([], D1) is False


def test_one_verified_binding_among_others_is_enough() -> None:
    bindings = [binding(D1, BindingStatus.REVOKED), verified(D2)]

    assert directory_is_bound(bindings, D2) is True
    assert directory_is_bound(bindings, D1) is False


def test_a_directory_is_matched_whatever_its_case() -> None:
    assert directory_is_bound([verified(D1)], D1.upper()) is True


@pytest.mark.parametrize("directory", ["", "not-a-guid", D1 + " ", None])
def test_text_that_is_not_a_directory_binds_nothing(directory: object) -> None:
    assert directory_is_bound([verified(D1)], directory) is False  # type: ignore[arg-type]


# ----------------------------------------------------------------------- may a token be issued


@pytest.mark.parametrize("role", [r for r in STAFF_ROLE_PRIORITY] + [Role.WALL])
def test_an_active_tenant_may_have_a_token_for_any_role_it_issues(role: Role) -> None:
    assert may_issue(make_tenant(TenantStatus.ACTIVE, id="tenant-a"), role) is True


def test_a_read_only_suspended_tenant_may_have_one_for_its_administrator_only() -> None:
    tenant = make_tenant(TenantStatus.SUSPENDED, id="tenant-a", suspend_mode=SuspendMode.READ_ONLY)

    assert may_issue(tenant, Role.TENANT_ADMIN) is True
    for role in (Role.LEAD, Role.ADVISOR, Role.NETWORK_ADMIN, Role.WALL):
        assert may_issue(tenant, role) is False, role


@pytest.mark.parametrize(
    "status",
    [
        TenantStatus.PROVISIONING,
        TenantStatus.OFFBOARDING,
        TenantStatus.OFFBOARDED,
        TenantStatus.PURGED,
    ],
)
def test_a_tenant_that_is_not_live_may_have_no_token(status: TenantStatus) -> None:
    for role in (Role.TENANT_ADMIN, Role.LEAD, Role.WALL):
        assert may_issue(make_tenant(status, id="tenant-a"), role) is False


def test_the_operator_role_never_gets_a_tenant_token_and_a_non_tenant_gets_none() -> None:
    assert may_issue(make_tenant(id="tenant-a"), Role.PLATFORM_OPERATOR) is False
    assert may_issue(object(), Role.LEAD) is False
    assert may_issue(None, Role.LEAD) is False
    assert may_issue(make_tenant(id="tenant-a"), "lead") is False  # type: ignore[arg-type]


# ----------------------------------------------------------------------- who a person is


def test_an_account_reference_is_stable_and_has_the_shape_the_network_records_take() -> None:
    reference = account_ref(KEY, D1, OID)

    assert reference == account_ref(KEY, D1, OID)
    assert ACCOUNT_REF_PATTERN.fullmatch(reference) is not None


def test_one_object_id_in_two_directories_is_two_people() -> None:
    assert account_ref(KEY, D1, OID) != account_ref(KEY, D2, OID)


def test_two_objects_in_one_directory_and_two_keys_give_two_references() -> None:
    other = "44444444-4444-4444-8444-444444444444"

    assert account_ref(KEY, D1, OID) != account_ref(KEY, D1, other)
    assert account_ref(KEY, D1, OID) != account_ref(OTHER_KEY, D1, OID)


def test_the_directory_and_the_object_cannot_be_swapped_to_the_same_reference() -> None:
    assert account_ref(KEY, D1, D2) != account_ref(KEY, D2, D1)


def test_an_account_reference_shows_neither_the_directory_nor_the_object() -> None:
    reference = account_ref(KEY, D1, OID)

    assert D1 not in reference and OID not in reference
    assert D1.replace("-", "") not in reference


def test_a_subject_is_per_tenant_and_stable() -> None:
    a = staff_subject(KEY, "tenant-a", D1, OID)

    assert a == staff_subject(KEY, "tenant-a", D1, OID)
    assert a != staff_subject(KEY, "tenant-b", D1, OID)
    assert a != staff_subject(KEY, "tenant-a", D2, OID)


def test_a_subject_is_a_short_opaque_word_that_is_not_the_account_reference() -> None:
    subject = staff_subject(KEY, "tenant-a", D1, OID)

    assert re.fullmatch(r"stf-[0-9a-f]{32}", subject)
    assert subject != account_ref(KEY, D1, OID)
    assert OID.replace("-", "") not in subject


@pytest.mark.parametrize("bad", [b"", b"short", b"x" * 31, "text", None])
def test_a_key_that_is_too_short_or_not_bytes_is_refused(bad: object) -> None:
    with pytest.raises(ValueError, match="key"):
        account_ref(bad, D1, OID)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="key"):
        staff_subject(bad, "tenant-a", D1, OID)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("directory", "object_id"),
    [("", OID), (D1, ""), ("not-a-guid", OID), (D1, "not-a-guid"), (D1, OID + "x"), (None, OID)],
)
def test_an_identity_that_is_not_two_guids_is_refused_without_naming_it(
    directory: object, object_id: object
) -> None:
    with pytest.raises(ValidationFailed) as refused:
        account_ref(KEY, directory, object_id)  # type: ignore[arg-type]

    assert "not-a-guid" not in str(refused.value)


def test_a_subject_needs_a_tenant_id() -> None:
    for bad in ("", "net-region-1", "platform", "A"):
        with pytest.raises(ValidationFailed):
            staff_subject(KEY, bad, D1, OID)


# ----------------------------------------------------------------------- lifetimes


def test_the_lifetimes_are_pinned() -> None:
    assert timedelta(hours=8) == STAFF_TOKEN_LIFETIME
    assert timedelta(hours=1) == OPERATOR_TOKEN_LIFETIME
    assert timedelta(hours=1) == WALL_TOKEN_LIFETIME


def test_an_expiry_is_the_instant_plus_the_lifetime_in_utc() -> None:
    assert expiry(NOW, timedelta(hours=8)) == datetime(2026, 10, 30, 17, 0, tzinfo=UTC)


def test_an_expiry_is_whole_seconds() -> None:
    moment = datetime(2026, 10, 30, 9, 0, 0, 750_000, tzinfo=UTC)

    assert expiry(moment, timedelta(hours=1)).microsecond == 0


def test_a_naive_instant_has_no_expiry() -> None:
    with pytest.raises(ValidationFailed):
        expiry(datetime(2026, 10, 30, 9, 0), timedelta(hours=1))
