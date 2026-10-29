"""The pure rules of the scope list (U23): who may change it, the reason a flag needs, the name
that is already listed, the London date of an entry and the order of the list.
"""

from datetime import UTC, date, datetime

import pytest

from diucs.application.actor import Actor
from diucs.application.use_cases.scope_list import (
    ScopeRow,
    check_reason,
    london_date,
    require_lead,
    same_name,
    scope_sort_key,
)
from diucs.domain.codes import Role, ScopeFlag, ServiceCategory
from diucs.domain.errors import NotAllowed, ValidationFailed
from tests.support.actors import ACTOR_TENANT


def actor(role: Role) -> Actor:
    return Actor(
        role=role,
        practitioner_id="person-1",
        device_id=None,
        channel="web",
        service_ids=frozenset(),
        tenant_id=ACTOR_TENANT,
    )


def row(name: str, flag: ScopeFlag, service_id: str = "svc-1") -> ScopeRow:
    return ScopeRow(
        service_id=service_id,
        name=name,
        category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
        flag=flag,
        reason="",
        registration_status=None,
    )


def test_the_lead_may_change_the_scope_list() -> None:
    require_lead(actor(Role.LEAD))


@pytest.mark.parametrize("role", [Role.ADVISOR, Role.CLINICAL, Role.REPORTER, Role.OWNER])
def test_no_other_role_may_change_the_scope_list(role: Role) -> None:
    with pytest.raises(NotAllowed):
        require_lead(actor(role))


def test_in_pilot_needs_no_reason() -> None:
    assert check_reason(ScopeFlag.IN_PILOT, "") == ""


@pytest.mark.parametrize("flag", [ScopeFlag.LATER, ScopeFlag.OUT_OF_SCOPE])
def test_a_flag_other_than_in_pilot_needs_a_reason(flag: ScopeFlag) -> None:
    with pytest.raises(ValidationFailed) as error:
        check_reason(flag, "")
    assert error.value.field == "reason"


@pytest.mark.parametrize("blank", [" ", "\t", "   \n"])
def test_a_blank_reason_is_no_reason(blank: str) -> None:
    with pytest.raises(ValidationFailed):
        check_reason(ScopeFlag.OUT_OF_SCOPE, blank)


def test_a_reason_is_kept_trimmed() -> None:
    assert check_reason(ScopeFlag.OUT_OF_SCOPE, "  Not on the Dorset pathway ") == (
        "Not on the Dorset pathway"
    )


def test_a_name_is_the_same_whatever_its_case_or_surrounding_space() -> None:
    assert same_name("UCR East", "  ucr east ")


def test_two_different_names_are_not_the_same() -> None:
    assert not same_name("UCR East", "UCR West")


def test_the_london_date_is_taken_in_london_not_in_utc() -> None:
    # 22:30 UTC on 1 June is 23:30 BST on 1 June; 23:30 UTC is 00:30 BST on 2 June.
    assert london_date(datetime(2026, 6, 1, 22, 30, tzinfo=UTC)) == date(2026, 6, 1)
    assert london_date(datetime(2026, 6, 1, 23, 30, tzinfo=UTC)) == date(2026, 6, 2)


def test_the_list_puts_in_pilot_first_then_later_then_out_of_scope_then_name() -> None:
    rows = [
        row("Zeta", ScopeFlag.OUT_OF_SCOPE, "z"),
        row("Beta", ScopeFlag.LATER, "b"),
        row("Gamma", ScopeFlag.IN_PILOT, "g"),
        row("Alpha", ScopeFlag.IN_PILOT, "a"),
    ]
    ordered = sorted(rows, key=scope_sort_key)
    assert [item.name for item in ordered] == ["Alpha", "Gamma", "Beta", "Zeta"]
