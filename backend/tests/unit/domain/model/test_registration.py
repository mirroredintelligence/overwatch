"""What the registration and scope-list records refuse (P13).

Each guard here is committed red before the guard exists (lesson L88, DEC-010). The refusals name
fields only; no value is echoed. Sample values are synthetic.
"""

from datetime import UTC, date, datetime
from typing import Any

import pytest

from diucs.domain.codes import CriteriaStatus, RegistrationStatus, ScopeFlag, ServiceCategory
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.registration import Registration, ScopeEntry

CREATED = datetime(2026, 10, 25, 12, 50, tzinfo=UTC)
SUBMITTED = datetime(2026, 10, 25, 13, 5, tzinfo=UTC)


def _registration(**overrides: Any) -> Registration:
    values: dict[str, Any] = {
        "id": "reg-ucr-east-1",
        "service_id": "svc-ucr-east",
        "status": RegistrationStatus.DRAFT,
        "requester_role_id": "role-applicant-1",
        "owner_role_id": None,
        "created_at": CREATED,
        "last_modified": CREATED,
    }
    values.update(overrides)
    return Registration(**values)


def _entry(**overrides: Any) -> ScopeEntry:
    values: dict[str, Any] = {
        "service_id": "svc-sdec-1",
        "name": "SDEC pilot",
        "category": ServiceCategory.SAME_DAY_EMERGENCY_CARE,
        "flag": ScopeFlag.IN_PILOT,
        "date": date(2026, 10, 25),
    }
    values.update(overrides)
    return ScopeEntry(**values)


# Registration status


def test_a_registration_status_must_be_a_registration_status_member() -> None:
    with pytest.raises(ValidationFailed):
        _registration(status="draft")


def test_a_criteria_status_with_the_same_value_is_refused() -> None:
    # Lesson L38: the two enums share the value "draft" and compare equal.
    assert CriteriaStatus.DRAFT == RegistrationStatus.DRAFT
    with pytest.raises(ValidationFailed):
        _registration(status=CriteriaStatus.DRAFT)


@pytest.mark.parametrize("field_name", ["created_at", "last_modified", "submitted_at"])
def test_every_datetime_must_be_timezone_aware(field_name: str) -> None:
    naive = datetime(2026, 10, 25, 13, 5)
    with pytest.raises(ValidationFailed):
        _registration(**{field_name: naive})


def test_a_submitted_registration_with_an_aware_time_is_accepted() -> None:
    assert _registration(status=RegistrationStatus.SUBMITTED, submitted_at=SUBMITTED)


# The draft: steps of scalar fields, nothing nested, nothing empty (DEC-001)


@pytest.mark.parametrize(
    "draft",
    [
        {"organisation": {}},
        {"organisation": "Dorset HealthCare"},
        {"organisation": {"ods": None}},
        {"organisation": {"ods": 1.5}},
        {"organisation": {"districts": ["DT4"]}},
        {"organisation": {"contact": {"phone": "x"}}},
        {1: {"ods": "RDY"}},
        {"organisation": {2: "RDY"}},
    ],
)
def test_a_draft_holds_steps_of_text_number_or_flag_fields_only(draft: dict[str, Any]) -> None:
    with pytest.raises(ValidationFailed):
        _registration(draft=draft)


def test_a_draft_with_text_numbers_and_flags_is_accepted() -> None:
    draft = {"organisation": {"name": "Dorset HealthCare", "ods": "RDY"}, "reporting": {"n": 3}}
    assert _registration(draft=draft).draft == draft


# Scope entries


def test_a_scope_flag_must_be_a_scope_flag_member() -> None:
    with pytest.raises(ValidationFailed):
        _entry(flag="in-pilot")


def test_a_category_must_be_a_service_category_member() -> None:
    with pytest.raises(ValidationFailed):
        _entry(category="same-day-emergency-care")


def test_the_scope_date_is_a_calendar_date_not_an_instant() -> None:
    # Lesson L48: datetime is a subclass of date, so an instant would pass a plain isinstance check.
    with pytest.raises(ValidationFailed):
        _entry(date=datetime(2026, 10, 25, 13, 5, tzinfo=UTC))


def test_a_scope_date_given_as_text_is_refused() -> None:
    # A date that arrives as text is not a calendar date, whatever it looks like.
    with pytest.raises(ValidationFailed):
        _entry(date="2026-10-25")


# Invitation (U24)


def _invitation(**overrides: Any) -> Any:
    from diucs.domain.model.registration import Invitation

    values: dict[str, Any] = {
        "id": "inv-1",
        "service_id": "svc-ucr-east",
        "registration_id": "reg-ucr-east-1",
        "requester_role_id": "role-lead-1",
        "invitee_id": "prac-invitee-1",
        "role_label": "Duty manager",
        "created_at": CREATED,
        "sent_at": CREATED,
        "expires_at": datetime(2026, 10, 27, 12, 50, tzinfo=UTC),
    }
    values.update(overrides)
    return Invitation(**values)


def test_an_invitation_with_its_ids_label_and_times_is_accepted() -> None:
    invitation = _invitation()
    assert invitation.role_label == "Duty manager"


@pytest.mark.parametrize("name", ["created_at", "sent_at", "expires_at"])
def test_every_invitation_time_must_be_timezone_aware(name: str) -> None:
    with pytest.raises(ValidationFailed) as raised:
        _invitation(**{name: datetime(2026, 10, 27, 12, 50)})
    assert raised.value.field == name


def test_an_invitation_must_expire_after_it_was_sent() -> None:
    with pytest.raises(ValidationFailed) as raised:
        _invitation(expires_at=CREATED)
    assert raised.value.field == "expires_at"


def test_an_invitation_cannot_be_sent_before_it_was_made() -> None:
    with pytest.raises(ValidationFailed) as raised:
        _invitation(sent_at=datetime(2026, 10, 25, 12, 49, tzinfo=UTC))
    assert raised.value.field == "sent_at"


@pytest.mark.parametrize("name", ["id", "service_id", "registration_id", "requester_role_id"])
def test_an_invitation_id_must_not_be_blank(name: str) -> None:
    with pytest.raises(ValidationFailed) as raised:
        _invitation(**{name: " "})
    assert raised.value.field == name


def test_an_invitee_must_be_named() -> None:
    with pytest.raises(ValidationFailed) as raised:
        _invitation(invitee_id="")
    assert raised.value.field == "invitee_id"


def test_a_role_label_must_not_carry_a_phone_number_or_a_postcode() -> None:
    for label in ("Ring 07700 900123 0123456", "Ward DT4 8XX"):
        with pytest.raises(ValidationFailed) as raised:
            _invitation(role_label=label)
        assert raised.value.field == "role_label"


def test_a_role_label_must_not_be_blank() -> None:
    with pytest.raises(ValidationFailed) as raised:
        _invitation(role_label="  ")
    assert raised.value.field == "role_label"
