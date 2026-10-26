"""Pure tests for the criteria mapping (P04).

ServiceCriteria <-> FHIR Basic with the ServiceCriteria profile. A version must survive the mapping
unchanged, and a value the mapping cannot hold exactly is refused, not stored. All values are
synthetic.
"""

from datetime import date
from typing import Any

import pytest

from diucs.adapters.outbound.graph_store.criteria_repository import (
    criteria_from_fhir,
    criteria_to_fhir,
)
from diucs.domain.codes import CODE_SYSTEM_NAMES, CriteriaStatus, NeedCategory, code_system_url
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.criteria import ServiceCriteria

UCR_WEST_V3 = ServiceCriteria(
    id="crit-ucr-west-v3",
    service_id="svc-ucr-west",
    version=3,
    status=CriteriaStatus.CURRENT,
    age_min=18,
    age_max=None,
    districts=frozenset({"DT1", "DT2", "DT3", "DT4"}),
    accepts=frozenset({NeedCategory.FALL_NO_INJURY, NeedCategory.FRAILTY}),
    excludes=frozenset(
        {
            NeedCategory.SUSPECTED_FRACTURE,
            NeedCategory.HEAD_INJURY_ANTICOAGULANTS,
            NeedCategory.IV_THERAPY,
        }
    ),
    review_by=date(2026, 12, 12),
    owner_role_id="role-ucr-west-criteria-owner",
    change_reason="Annual review",
)


def test_ucr_west_v3_survives_the_mapping() -> None:
    assert criteria_from_fhir(criteria_to_fhir(UCR_WEST_V3)) == UCR_WEST_V3


def test_the_fhir_form_carries_no_meta_and_no_json_text() -> None:
    resource = criteria_to_fhir(UCR_WEST_V3)
    assert resource["resourceType"] == "Basic"
    assert "meta" not in resource
    assert all(
        not (isinstance(value, str) and value.lstrip()[:1] in "{[") for value in resource.values()
    )


def test_a_version_with_no_needs_no_districts_and_no_upper_age_round_trips() -> None:
    bare = ServiceCriteria(
        id="crit-bare-v1",
        service_id="svc-ucr-west",
        version=1,
        status=CriteriaStatus.DRAFT,
        age_min=0,
        age_max=None,
        districts=frozenset(),
        accepts=frozenset(),
        excludes=frozenset(),
        review_by=date(2027, 1, 1),
        owner_role_id="role-ucr-west-criteria-owner",
    )
    assert criteria_from_fhir(criteria_to_fhir(bare)) == bare


def test_a_need_coded_in_another_system_is_refused() -> None:
    resource = criteria_to_fhir(UCR_WEST_V3)
    concept = resource["acceptsNeed"][0]
    # The code is a real need, but its system is the criteria-status system, not the need system.
    concept["coding"][0]["system"] = code_system_url(CODE_SYSTEM_NAMES[CriteriaStatus])
    with pytest.raises(ValidationFailed) as refused:
        criteria_from_fhir(resource)
    assert refused.value.args[0].startswith("acceptsNeed")


@pytest.mark.parametrize(
    "field, value",
    [
        ("status", "approved"),
        ("reviewBy", "12/12/2026"),
        ("ageMin", -1),
    ],
)
def test_a_malformed_value_is_refused_by_name(field: str, value: Any) -> None:
    resource = criteria_to_fhir(UCR_WEST_V3)
    resource[field] = value
    with pytest.raises(ValidationFailed) as refused:
        criteria_from_fhir(resource)
    assert refused.value.args[0].startswith(field)
