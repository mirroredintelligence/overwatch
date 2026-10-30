"""The date a criteria version was changed (W7B B): set when the owner proposes a change and again
when it is approved, kept by the stored form, and refused when it is not a calendar date."""

from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from diucs.adapters.outbound.graph_store.criteria_repository import (
    criteria_from_fhir,
    criteria_to_fhir,
)
from diucs.application.use_cases.criteria import CriteriaValues, approved_versions, pending_version
from diucs.domain.codes import CriteriaStatus, NeedCategory
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.criteria import ServiceCriteria

CURRENT = ServiceCriteria(
    id="crit-2",
    service_id="svc-1",
    version=2,
    status=CriteriaStatus.CURRENT,
    age_min=18,
    age_max=None,
    districts=frozenset({"DT4"}),
    accepts=frozenset({NeedCategory.FRAILTY}),
    excludes=frozenset(),
    review_by=date(2027, 1, 1),
    owner_role_id="role-owner",
    changed_on=date(2026, 9, 12),
)
VALUES = CriteriaValues(
    age_min=16,
    age_max=None,
    accepts=frozenset({NeedCategory.FRAILTY}),
    excludes=frozenset(),
    districts=frozenset({"DT4"}),
)


def test_a_proposed_change_carries_the_day_it_was_proposed() -> None:
    pending = pending_version(
        current=CURRENT,
        new_id="crit-3",
        owner_role_id="role-owner",
        values=VALUES,
        change_reason="Younger adults.",
        review_months=6,
        today=date(2026, 10, 30),
    )

    assert pending.changed_on == date(2026, 10, 30)


def test_approval_moves_the_date_to_the_day_it_was_approved() -> None:
    pending = replace(
        CURRENT,
        id="crit-3",
        version=3,
        status=CriteriaStatus.PENDING_APPROVAL,
        supersedes_id="crit-2",
        review_months=6,
        changed_on=date(2026, 10, 28),
    )

    old, new = approved_versions(CURRENT, pending, date(2026, 10, 30))

    assert new.changed_on == date(2026, 10, 30)
    assert old is not None and old.changed_on == date(2026, 9, 12)


def test_the_stored_form_keeps_the_date_and_an_old_version_has_none() -> None:
    resource = criteria_to_fhir(CURRENT)
    assert resource["changedOn"] == "2026-09-12"
    assert criteria_from_fhir({**resource, "meta": {"versionId": "1"}}).changed_on == date(
        2026, 9, 12
    )

    del resource["changedOn"]
    assert criteria_from_fhir({**resource, "meta": {"versionId": "1"}}).changed_on is None
    assert "changedOn" not in criteria_to_fhir(replace(CURRENT, changed_on=None))


@pytest.mark.parametrize("bad", ["2026-09-12", datetime(2026, 9, 12, tzinfo=UTC), 20260912])
def test_a_date_that_is_not_a_calendar_date_is_refused(bad: object) -> None:
    with pytest.raises(ValidationFailed) as refusal:
        replace(CURRENT, changed_on=bad)  # type: ignore[arg-type]
    assert refusal.value.field == "changed_on"
