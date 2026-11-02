"""The names and checks of the Entra groups Overwatch makes (DEC-1317). Pure."""

import pytest

from overwatch.domain.codes import Role
from overwatch.domain.errors import ValidationFailed
from overwatch.domain.rules.entra_groups import (
    OPERATOR_GROUP_ROLES,
    OVERWATCH_MEMBER_APP_ROLE_ID,
    OVERWATCH_MEMBER_APP_ROLE_VALUE,
    check_search_term,
    group_name,
    group_prefix,
    hash_user_ref,
    is_managed_name,
    require_managed_name,
    role_of_name,
    role_slug,
)

SECRET = b"test-only-secret-0123456789abcdef"


def test_the_app_role_id_is_the_one_declared_in_the_azure_app_registration() -> None:
    # Declared in Azure, not read from it (the tests make no Azure call): app registration
    # 7fb43bde-6a6d-4aed-9cac-9118de48ab52, App roles, displayName "Overwatch member", value
    # `Overwatch.Member`, id 52475a88-b5cd-4e30-9090-316d1c29672f. Checked in Azure on 2026-11-01.
    assert OVERWATCH_MEMBER_APP_ROLE_ID == "52475a88-b5cd-4e30-9090-316d1c29672f"
    assert OVERWATCH_MEMBER_APP_ROLE_VALUE == "Overwatch.Member"


def test_the_prefix_is_the_ods_code_then_overwatch() -> None:
    assert group_prefix("F81044", "new-org") == "F81044_overwatch_"


def test_a_tenant_with_no_ods_code_uses_its_tenant_id() -> None:
    assert group_prefix(None, "new-org") == "new-org_overwatch_"
    assert group_prefix("", "new-org") == "new-org_overwatch_"


@pytest.mark.parametrize("bad", ["a b", "x_y", "-lead", "a/../b", "x" * 65, "o'brien"])
def test_an_ods_or_id_that_could_not_be_part_of_a_name_is_refused(bad: str) -> None:
    with pytest.raises(ValidationFailed):
        group_prefix(bad, "new-org")


def test_the_administrators_group_and_each_roles_group_are_built_from_the_prefix() -> None:
    prefix = group_prefix("F81044", "new-org")
    assert group_name(prefix, Role.TENANT_ADMIN) == "F81044_overwatch_tenant-admin"
    assert group_name(prefix, Role.LEAD) == "F81044_overwatch_lead"
    assert group_name(prefix, Role.CLINICAL) == "F81044_overwatch_clinical"


@pytest.mark.parametrize(
    "role",
    [Role.PLATFORM_OPERATOR, Role.SUPPORT, Role.REPORTER, Role.WALL, Role.NETWORK_ADMIN, "lead"],
)
def test_there_is_no_group_for_the_platform_operator_or_a_role_a_directory_cannot_give(
    role: object,
) -> None:
    with pytest.raises(ValidationFailed):
        group_name("F81044_overwatch_", role)  # type: ignore[arg-type]
    with pytest.raises(ValidationFailed):
        role_slug(role)  # type: ignore[arg-type]


def test_the_operator_may_ask_for_every_staff_role_but_the_two_administrators() -> None:
    assert Role.TENANT_ADMIN not in OPERATOR_GROUP_ROLES
    assert Role.NETWORK_ADMIN not in OPERATOR_GROUP_ROLES
    assert Role.PLATFORM_OPERATOR not in OPERATOR_GROUP_ROLES
    assert {Role.ADVISOR, Role.CLINICAL, Role.LEAD} <= OPERATOR_GROUP_ROLES


@pytest.mark.parametrize(
    "name",
    [
        "Domain Admins",
        "F81044_overwatch",  # the prefix with nothing after it
        "f81044_overwatch_lead",  # another case is another prefix
        "XF81044_overwatch_lead",
        "OTHER_overwatch_lead",
        "F81044_overwatch_le ad",
        "F81044_overwatch_" + "x" * 120,
        "",
        None,
        7,
    ],
)
def test_a_name_that_is_not_built_from_the_prefix_is_refused_and_not_echoed(name: object) -> None:
    assert not is_managed_name(name, "F81044_overwatch_")
    with pytest.raises(ValidationFailed) as refused:
        require_managed_name(name, "F81044_overwatch_")
    assert str(name) not in refused.value.message or str(name) == ""


def test_a_managed_name_maps_back_to_its_role() -> None:
    prefix = "F81044_overwatch_"
    assert role_of_name("F81044_overwatch_tenant-admin", prefix) is Role.TENANT_ADMIN
    assert role_of_name("F81044_overwatch_lead", prefix) is Role.LEAD
    assert role_of_name("F81044_overwatch_something-else", prefix) is None
    assert role_of_name("OTHER_overwatch_lead", prefix) is None


def test_a_user_reference_is_a_keyed_hash_that_differs_by_secret_and_holds_no_id() -> None:
    user = "aaaaaaaa-0000-4000-8000-000000000001"
    one = hash_user_ref(user, SECRET)
    assert one == hash_user_ref(user.upper(), SECRET)
    assert one != hash_user_ref(user, SECRET + b"x")
    assert len(one) == 64 and user not in one


# -- the people lookup (DEC-1325) ---------------------------------------------------------------


@pytest.mark.parametrize("term", ["ja", "jane", "O'Neil", "jane.m@example", "j+x_y-z", " jane "])
def test_a_plain_search_term_is_kept_trimmed(term: str) -> None:
    assert check_search_term(term) == term.strip()


@pytest.mark.parametrize(
    "term",
    [
        "",
        " ",
        "a",
        " a ",
        "x" * 65,
        "jane;drop",
        "a<b",
        "name}",
        "jane" + chr(10) + "x",
        "j" + chr(233),
        None,
        7,
    ],
)
def test_a_term_that_is_short_long_or_not_plain_is_refused_without_echoing_it(term: object) -> None:
    with pytest.raises(ValidationFailed) as refused:
        check_search_term(term)
    assert "drop" not in str(refused.value) and "x" * 65 not in str(refused.value)
