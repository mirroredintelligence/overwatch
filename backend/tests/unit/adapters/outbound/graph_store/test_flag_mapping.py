"""Pure tests for the service flag mapping (P14): ServiceFlag <-> FHIR Basic with profile ServiceFlag.

A flag must survive the mapping unchanged, and a value the mapping cannot hold exactly is refused,
never stored. All values are synthetic.
"""

from datetime import UTC, datetime
from typing import Any

import pytest

from diucs.adapters.outbound.graph_store.flag_repository import (
    service_flag_from_fhir,
    service_flag_id,
    service_flag_to_fhir,
)
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.flags import (
    SERVICE_FLAG_CRITERIA_OVERDUE,
    SERVICE_FLAG_SUSPENDED,
    ServiceFlag,
)

SUSPENDED = ServiceFlag(
    service_id="svc-ucr-west",
    code=SERVICE_FLAG_SUSPENDED,
    active=True,
    reason="Staffing shortfall",
    actor_id="role-ucr-west-lead",
    at=datetime(2026, 10, 25, 9, 14, tzinfo=UTC),
)
OVERDUE_INACTIVE = ServiceFlag(
    service_id="svc-ucr-east",
    code=SERVICE_FLAG_CRITERIA_OVERDUE,
    active=False,
    reason="Review date passed",
    actor_id="role-ucr-east-owner",
    at=datetime(2026, 10, 26, 8, 0, tzinfo=UTC),
)


@pytest.mark.parametrize("flag", [SUSPENDED, OVERDUE_INACTIVE])
def test_a_service_flag_survives_the_mapping(flag: ServiceFlag) -> None:
    assert service_flag_from_fhir(service_flag_to_fhir(flag)) == flag


def test_the_fhir_form_is_a_basic_with_no_meta_and_no_map_or_json_values() -> None:
    resource = service_flag_to_fhir(SUSPENDED)
    assert resource["resourceType"] == "Basic"
    assert "meta" not in resource
    assert resource["subject"] == {"reference": "HealthcareService/svc-ucr-west"}
    for value in resource.values():
        assert not isinstance(value, dict) or set(value) == {"reference"}
        assert not (isinstance(value, str) and value.lstrip()[:1] in "{[")


def test_one_flag_id_per_service_and_code() -> None:
    suspended = service_flag_id("svc-ucr-west", SERVICE_FLAG_SUSPENDED)
    overdue = service_flag_id("svc-ucr-west", SERVICE_FLAG_CRITERIA_OVERDUE)
    assert suspended != overdue
    assert suspended == service_flag_id("svc-ucr-west", SERVICE_FLAG_SUSPENDED)
    assert service_flag_id("svc-ucr-east", SERVICE_FLAG_SUSPENDED) != suspended


def test_a_resource_with_an_element_the_flag_profile_does_not_hold_is_refused() -> None:
    resource: dict[str, Any] = {**service_flag_to_fhir(SUSPENDED), "author": {"reference": "x"}}
    with pytest.raises(ValidationFailed):
        service_flag_from_fhir(resource)


def test_a_resource_with_an_unknown_code_is_refused() -> None:
    resource = {**service_flag_to_fhir(SUSPENDED), "code": "closed"}
    with pytest.raises(ValidationFailed) as refused:
        service_flag_from_fhir(resource)
    assert refused.value.field == "code"


def test_a_resource_with_a_status_that_is_not_active_or_inactive_is_refused() -> None:
    resource = {**service_flag_to_fhir(SUSPENDED), "status": "final"}
    with pytest.raises(ValidationFailed) as refused:
        service_flag_from_fhir(resource)
    assert refused.value.field == "status"
