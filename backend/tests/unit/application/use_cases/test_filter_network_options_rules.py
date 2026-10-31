"""The pure part of FilterNetworkOptions (KI-349): a projected criteria version as the hard filter
reads it. The storage and the registry are in
tests/integration/application/test_filter_network_options.py."""

from datetime import date

from diucs.application.use_cases.filter_network_options import criteria_of
from diucs.domain.codes import AgeBand, CriteriaStatus, NeedCategory
from diucs.domain.rules.criteria_filter import check_hard_criteria
from diucs.domain.rules.projection import CriteriaProjection

PROJECTION = CriteriaProjection(
    source_criteria_id="crit-secret-1",
    source_service_id="svc-secret-1",
    version=4,
    age_min=18,
    age_max=None,
    districts=("DT1", "DT4"),
    accepts=(NeedCategory.FALL_NO_INJURY, NeedCategory.FRAILTY),
    excludes=(NeedCategory.IV_THERAPY,),
    review_by=date(2027, 4, 29),
)


def test_the_criteria_are_named_by_the_listing_and_never_by_the_members_own_ids() -> None:
    criteria = criteria_of("lst-abc-1", PROJECTION)

    assert criteria.service_id == "lst-abc-1"
    assert criteria.id == "lst-abc-1-v4"
    assert "secret" not in repr(criteria)


def test_a_projected_version_is_current_and_keeps_its_ages_districts_and_needs() -> None:
    criteria = criteria_of("lst-abc-1", PROJECTION)

    assert criteria.status is CriteriaStatus.CURRENT
    assert criteria.version == 4
    assert criteria.districts == frozenset({"DT1", "DT4"})
    assert criteria.excludes == frozenset({NeedCategory.IV_THERAPY})


def test_the_filter_passes_a_case_the_projection_covers_and_refuses_one_it_does_not() -> None:
    criteria = criteria_of("lst-abc-1", PROJECTION)

    covered = check_hard_criteria(criteria, AgeBand.A80_PLUS, "DT4", (NeedCategory.FRAILTY,))
    elsewhere = check_hard_criteria(criteria, AgeBand.A80_PLUS, "BH1", (NeedCategory.FRAILTY,))
    excluded = check_hard_criteria(criteria, AgeBand.A80_PLUS, "DT4", (NeedCategory.IV_THERAPY,))

    assert covered.passes
    assert not elsewhere.passes
    assert not excluded.passes
