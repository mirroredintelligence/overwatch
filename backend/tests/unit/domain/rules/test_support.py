"""Support access rules (O06, domain-rules 7 and the support section of the data model). Pure: no
clock, no store. Sample values only."""

from datetime import UTC, datetime, timedelta

import pytest

from diucs.domain.codes import PractitionerRoleCode as Code
from diucs.domain.codes import Role
from diucs.domain.model.people import PractitionerRole
from diucs.domain.rules.support import (
    access_window,
    code_window,
    hash_support_code,
    is_lead,
    may_open_support,
    normalise_support_code,
    support_code_usable,
)
from diucs.domain.rules.tokens import hash_token

NOW = datetime(2026, 10, 29, 9, 0, tzinfo=UTC)
SECRET = b"support-code-test-secret-0123456789"


@pytest.mark.parametrize(
    ("typed", "canonical"),
    [
        ("ABCD-EFGH", "ABCD-EFGH"),
        ("abcd-efgh", "ABCD-EFGH"),
        ("ABCD EFGH", "ABCD-EFGH"),
        ("ABCDEFGH", "ABCD-EFGH"),
        (" abcd - efgh ", "ABCD-EFGH"),
    ],
)
def test_a_typed_code_is_normalised_to_its_display_form(typed: str, canonical: str) -> None:
    assert normalise_support_code(typed) == canonical


@pytest.mark.parametrize(
    "typed",
    [
        "ABCD-EFG",  # too short
        "ABCD-EFGHI",  # too long
        "ABCD-EFG0",  # 0 is not in the support alphabet
        "ABCD-EFGI",  # I is not in the support alphabet
        "ABCD-EFGO",  # O is not in the support alphabet
        "ABCD-EFG!",  # not a letter or digit
        "",
    ],
)
def test_text_that_is_not_a_support_code_is_refused(typed: str) -> None:
    assert normalise_support_code(typed) is None


def test_a_non_text_value_is_refused() -> None:
    assert normalise_support_code(12345678) is None
    assert normalise_support_code(None) is None


def test_the_stored_hash_is_the_keyed_token_hash_and_does_not_contain_the_code() -> None:
    code = "ABCD-EFGH"

    stored = hash_support_code(code, SECRET)

    assert stored == hash_token(code, SECRET)
    assert len(stored) == 64
    assert "ABCD" not in stored and "EFGH" not in stored


def test_a_different_code_or_secret_gives_a_different_hash() -> None:
    assert hash_support_code("ABCD-EFGH", SECRET) != hash_support_code("ABCD-EFGK", SECRET)
    assert hash_support_code("ABCD-EFGH", SECRET) != hash_support_code(
        "ABCD-EFGH", b"another-secret-value-0123456789"
    )


def test_a_code_is_valid_for_four_hours_and_an_open_for_one_hour() -> None:
    assert code_window(NOW) == NOW + timedelta(hours=4)
    assert access_window(NOW) == NOW + timedelta(hours=1)


def test_a_code_is_usable_until_its_expiry_and_not_at_it() -> None:
    expires = NOW + timedelta(hours=4)

    assert support_code_usable(expires, None, expires - timedelta(seconds=1)) is True
    assert support_code_usable(expires, None, expires) is False
    assert support_code_usable(expires, None, expires + timedelta(seconds=1)) is False


def test_a_stopped_code_is_not_usable_even_before_its_expiry() -> None:
    expires = NOW + timedelta(hours=4)

    assert support_code_usable(expires, NOW, NOW) is False


def test_a_naive_time_is_refused_rather_than_compared() -> None:
    with pytest.raises(ValueError):
        support_code_usable(datetime(2026, 10, 29, 13, 0), None, NOW)


def _role(code: Code, active: bool = True) -> PractitionerRole:
    return PractitionerRole(
        id="r-1",
        practitioner_id="p-1",
        service_id="svc-1",
        code=code,
        active=active,
        channel=None,
        period_start=NOW - timedelta(days=30),
    )


@pytest.mark.parametrize("code", [Code.SHIFT_LEAD, Code.CLINICAL_LEAD])
def test_an_active_practitioner_with_a_lead_role_is_a_lead(code: Code) -> None:
    assert is_lead([_role(code)], practitioner_active=True) is True


@pytest.mark.parametrize("code", [Code.COORDINATOR, Code.REVIEWER, Code.DUTY_MANAGER])
def test_a_role_that_is_not_a_lead_role_does_not_approve(code: Code) -> None:
    assert is_lead([_role(code)], practitioner_active=True) is False


def test_an_inactive_lead_role_does_not_approve() -> None:
    assert is_lead([_role(Code.SHIFT_LEAD, active=False)], practitioner_active=True) is False


def test_an_inactive_practitioner_does_not_approve_even_with_a_lead_role() -> None:
    assert is_lead([_role(Code.SHIFT_LEAD)], practitioner_active=False) is False


def test_a_practitioner_with_no_roles_does_not_approve() -> None:
    assert is_lead([], practitioner_active=True) is False


def test_only_the_support_role_may_open_a_session() -> None:
    assert may_open_support(Role.SUPPORT) is True
    for role in Role:
        if role is not Role.SUPPORT:
            assert may_open_support(role) is False
