"""The pure rules of the criteria use cases (U30): the pending version, who may change and approve,
the approval, and the review date. No Neo4j: the use cases are tested in
tests/integration/application/test_criteria.py."""

from datetime import UTC, date, datetime

import pytest

from diucs.application.use_cases.criteria import (
    CriteriaValues,
    approved_versions,
    check_may_approve,
    check_may_change,
    confirmed_review_by,
    pending_version,
)
from diucs.domain.codes import Channel, CriteriaStatus, NeedCategory, PractitionerRoleCode
from diucs.domain.errors import InvalidTransition, NotAllowed, ValidationFailed
from diucs.domain.model.criteria import ServiceCriteria
from diucs.domain.model.people import PractitionerRole

NOW = datetime(2026, 10, 23, 13, 0, tzinfo=UTC)
TODAY = date(2026, 10, 23)
SERVICE = "svc-ucr-west"
OWNER_ROLE = "role-owner-west"


def _version(
    number: int,
    status: CriteriaStatus,
    *,
    age_min: int = 18,
    supersedes: str | None = None,
    review_months: int | None = None,
) -> ServiceCriteria:
    return ServiceCriteria(
        id=f"crit-{number}",
        service_id=SERVICE,
        version=number,
        status=status,
        age_min=age_min,
        age_max=None,
        districts=frozenset({"DT4"}),
        accepts=frozenset({NeedCategory.FRAILTY}),
        excludes=frozenset(),
        review_by=date(2027, 1, 1),
        owner_role_id=OWNER_ROLE,
        supersedes_id=supersedes,
        review_months=review_months,
    )


def _values(age_min: int = 16) -> CriteriaValues:
    return CriteriaValues(
        age_min=age_min,
        age_max=None,
        accepts=frozenset({NeedCategory.FRAILTY}),
        excludes=frozenset(),
        districts=frozenset({"DT4"}),
    )


def _role(
    role_id: str,
    code: PractitionerRoleCode,
    *,
    service_id: str | None = SERVICE,
    active: bool = True,
    practitioner: str = "prac-1",
) -> PractitionerRole:
    return PractitionerRole(
        id=role_id,
        practitioner_id=practitioner,
        service_id=service_id,
        code=code,
        active=active,
        channel=Channel.TEXT,
        period_start=datetime(2026, 1, 1, tzinfo=UTC),
    )


# --- the pending version ---------------------------------------------------------------------


def test_the_pending_version_is_the_next_number_with_the_changes_and_the_old_version_as_its_base():
    pending = pending_version(
        current=_version(3, CriteriaStatus.CURRENT),
        new_id="crit-4",
        owner_role_id=OWNER_ROLE,
        values=_values(age_min=16),
        change_reason="lower youngest age",
        review_months=6,
        today=TODAY,
    )
    assert pending.version == 4
    assert pending.status is CriteriaStatus.PENDING_APPROVAL
    assert pending.supersedes_id == "crit-3"
    assert pending.age_min == 16
    assert pending.change_reason == "lower youngest age"
    assert pending.review_months == 6
    assert pending.review_by == date(2027, 4, 23)


@pytest.mark.parametrize(("months", "expected"), [(3, date(2027, 1, 23)), (12, date(2027, 10, 23))])
def test_the_review_again_choice_is_three_six_or_twelve_months_from_the_change(months, expected):
    pending = pending_version(
        current=_version(1, CriteriaStatus.CURRENT),
        new_id="crit-2",
        owner_role_id=OWNER_ROLE,
        values=_values(),
        change_reason="r",
        review_months=months,
        today=TODAY,
    )
    assert pending.review_by == expected


@pytest.mark.parametrize("months", [0, 1, 2, 4, 5, 7, 11, 13, -3])
def test_any_other_review_period_is_refused(months):
    with pytest.raises(ValidationFailed):
        pending_version(
            current=_version(1, CriteriaStatus.CURRENT),
            new_id="crit-2",
            owner_role_id=OWNER_ROLE,
            values=_values(),
            change_reason="r",
            review_months=months,
            today=TODAY,
        )


def test_a_review_period_given_as_a_boolean_is_refused():
    with pytest.raises(ValidationFailed):
        pending_version(
            current=_version(1, CriteriaStatus.CURRENT),
            new_id="crit-2",
            owner_role_id=OWNER_ROLE,
            values=_values(),
            change_reason="r",
            review_months=True,  # type: ignore[arg-type]
            today=TODAY,
        )


def test_a_youngest_age_above_the_oldest_is_refused_by_the_model():
    bad = CriteriaValues(
        age_min=30,
        age_max=20,
        accepts=frozenset({NeedCategory.FRAILTY}),
        excludes=frozenset(),
        districts=frozenset({"DT4"}),
    )
    with pytest.raises(ValidationFailed):
        pending_version(
            current=_version(1, CriteriaStatus.CURRENT),
            new_id="crit-2",
            owner_role_id=OWNER_ROLE,
            values=bad,
            change_reason="r",
            review_months=3,
            today=TODAY,
        )


# --- who may change ---------------------------------------------------------------------------


def test_the_owner_of_the_service_may_change_its_criteria():
    check_may_change(
        [_role(OWNER_ROLE, PractitionerRoleCode.CRITERIA_OWNER)],
        service_id=SERVICE,
        owner_role_id=OWNER_ROLE,
        now=NOW,
    )


def test_someone_who_holds_no_active_owner_role_for_the_service_may_not_change_it():
    roles = [
        _role(OWNER_ROLE, PractitionerRoleCode.CRITERIA_OWNER, active=False),
        _role(OWNER_ROLE + "-other", PractitionerRoleCode.CRITERIA_OWNER, service_id="svc-other"),
        _role("role-shift", PractitionerRoleCode.SHIFT_LEAD),
    ]
    with pytest.raises(NotAllowed):
        check_may_change(roles, service_id=SERVICE, owner_role_id=OWNER_ROLE, now=NOW)


def test_a_practitioner_with_no_roles_may_not_change_criteria():
    with pytest.raises(NotAllowed):
        check_may_change([], service_id=SERVICE, owner_role_id=OWNER_ROLE, now=NOW)


# --- who may approve --------------------------------------------------------------------------


def test_a_clinical_lead_who_is_not_the_author_may_approve():
    check_may_approve(
        [_role("role-lead", PractitionerRoleCode.CLINICAL_LEAD, practitioner="prac-2")],
        service_id=SERVICE,
        author_role_id=OWNER_ROLE,
        now=NOW,
    )


def test_the_author_may_not_approve_their_own_change():
    roles = [
        _role(OWNER_ROLE, PractitionerRoleCode.CRITERIA_OWNER),
        _role("role-lead", PractitionerRoleCode.CLINICAL_LEAD),
    ]
    with pytest.raises(NotAllowed):
        check_may_approve(roles, service_id=SERVICE, author_role_id=OWNER_ROLE, now=NOW)


def test_someone_who_is_not_a_clinical_lead_may_not_approve():
    roles = [_role("role-coord", PractitionerRoleCode.COORDINATOR)]
    with pytest.raises(NotAllowed):
        check_may_approve(roles, service_id=SERVICE, author_role_id=OWNER_ROLE, now=NOW)


def test_an_inactive_clinical_lead_may_not_approve():
    roles = [_role("role-lead", PractitionerRoleCode.CLINICAL_LEAD, active=False)]
    with pytest.raises(NotAllowed):
        check_may_approve(roles, service_id=SERVICE, author_role_id=OWNER_ROLE, now=NOW)


def test_a_clinical_lead_of_another_service_may_not_approve_this_one():
    roles = [_role("role-lead", PractitionerRoleCode.CLINICAL_LEAD, service_id="svc-other")]
    with pytest.raises(NotAllowed):
        check_may_approve(roles, service_id=SERVICE, author_role_id=OWNER_ROLE, now=NOW)


def test_a_first_version_with_no_author_role_can_be_approved_by_any_clinical_lead():
    check_may_approve(
        [_role("role-lead", PractitionerRoleCode.CLINICAL_LEAD)],
        service_id=SERVICE,
        author_role_id=None,
        now=NOW,
    )


# --- approval ---------------------------------------------------------------------------------


def test_approval_makes_the_pending_version_current_and_supersedes_the_old_one():
    current = _version(3, CriteriaStatus.CURRENT)
    pending = pending_version(
        current=current,
        new_id="crit-4",
        owner_role_id=OWNER_ROLE,
        values=_values(),
        change_reason="r",
        review_months=6,
        today=TODAY,
    )
    old, new = approved_versions(current, pending, date(2026, 10, 26))
    assert old is not None and old.status is CriteriaStatus.SUPERSEDED and old.id == "crit-3"
    assert new.status is CriteriaStatus.CURRENT and new.id == "crit-4"


def test_approval_sets_review_by_to_the_approval_date_plus_the_chosen_months():
    current = _version(3, CriteriaStatus.CURRENT)
    pending = pending_version(
        current=current,
        new_id="crit-4",
        owner_role_id=OWNER_ROLE,
        values=_values(),
        change_reason="r",
        review_months=6,
        today=TODAY,
    )
    _, new = approved_versions(current, pending, date(2026, 11, 2))
    assert new.review_by == date(2027, 5, 2)


def test_approving_a_version_that_is_not_pending_is_refused():
    current = _version(3, CriteriaStatus.CURRENT)
    draft = _version(4, CriteriaStatus.DRAFT, supersedes="crit-3", review_months=3)
    with pytest.raises(InvalidTransition):
        approved_versions(current, draft, TODAY)


def test_approval_without_a_chosen_review_period_is_refused():
    current = _version(3, CriteriaStatus.CURRENT)
    pending = _version(4, CriteriaStatus.PENDING_APPROVAL, supersedes="crit-3")
    with pytest.raises(ValidationFailed):
        approved_versions(current, pending, TODAY)


def test_a_first_version_with_no_current_one_becomes_current_with_nothing_superseded():
    pending = _version(1, CriteriaStatus.PENDING_APPROVAL, review_months=3)
    old, new = approved_versions(None, pending, TODAY)
    assert old is None
    assert new.status is CriteriaStatus.CURRENT
    assert new.review_by == date(2027, 1, 23)


# --- confirmation -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("months", "expected"),
    [(3, date(2027, 1, 23)), (6, date(2027, 4, 23)), (12, date(2027, 10, 23))],
)
def test_confirming_sets_review_by_from_today(months, expected):
    assert confirmed_review_by(date(2026, 10, 23), months) == expected


def test_confirming_on_a_month_end_clamps_to_the_last_day_of_the_month():
    assert confirmed_review_by(date(2026, 8, 31), 6) == date(2027, 2, 28)


def test_confirming_refuses_an_instant_as_the_day():
    with pytest.raises(ValidationFailed):
        confirmed_review_by(NOW, 6)  # type: ignore[arg-type]


def test_confirming_refuses_a_period_other_than_three_six_or_twelve():
    with pytest.raises(ValidationFailed):
        confirmed_review_by(TODAY, 4)


def test_the_status_enum_is_not_matched_by_value_alone():
    # CriteriaStatus.DRAFT and RegistrationStatus.DRAFT are both "draft" (lesson L38): a
    # registration status must not pass as a criteria status in a version.
    from diucs.domain.codes import RegistrationStatus

    assert CriteriaStatus.DRAFT == RegistrationStatus.DRAFT
    with pytest.raises(ValidationFailed):
        _version(2, RegistrationStatus.DRAFT)  # type: ignore[arg-type]
