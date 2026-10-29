"""The chosen review period survives the criteria mapper (U30, DEC-174): a pending version that
lost it could not be approved, so the round trip is pinned here without Neo4j."""

from datetime import date

import pytest

from diucs.adapters.outbound.graph_store.criteria_repository import (
    criteria_from_fhir,
    criteria_to_fhir,
)
from diucs.domain.codes import CriteriaStatus, NeedCategory
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.criteria import ServiceCriteria


def _criteria(review_months: int | None) -> ServiceCriteria:
    return ServiceCriteria(
        id="crit-4",
        service_id="ucr-west",
        version=4,
        status=CriteriaStatus.PENDING_APPROVAL,
        age_min=16,
        age_max=None,
        districts=frozenset({"DT4"}),
        accepts=frozenset({NeedCategory.FRAILTY}),
        excludes=frozenset(),
        review_by=date(2027, 4, 23),
        owner_role_id="role-owner-west",
        change_reason="lower youngest age",
        supersedes_id="crit-3",
        review_months=review_months,
    )


@pytest.mark.parametrize("months", [3, 6, 12])
def test_the_chosen_review_period_round_trips(months: int) -> None:
    original = _criteria(months)
    assert criteria_from_fhir(criteria_to_fhir(original)) == original


def test_a_version_with_no_chosen_period_stores_no_element_and_reads_back_as_none() -> None:
    resource = criteria_to_fhir(_criteria(None))
    assert "reviewMonths" not in resource
    assert criteria_from_fhir(resource).review_months is None


@pytest.mark.parametrize("months", [0, 4, 13])
def test_a_stored_period_that_is_not_a_choice_is_refused_on_read(months: int) -> None:
    resource = criteria_to_fhir(_criteria(3))
    resource["reviewMonths"] = months
    with pytest.raises(ValidationFailed):
        criteria_from_fhir(resource)
