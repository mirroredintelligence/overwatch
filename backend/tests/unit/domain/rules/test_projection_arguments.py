"""Arguments that are not what the projection builders and the board take (TEN-052): each is
refused with `ValidationFailed` and nothing is built (fail closed)."""

from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest

from diucs.domain.errors import ValidationFailed
from diucs.domain.messages.privacy_guard import find_forbidden_keys, scan_value
from diucs.domain.model.network import GrantScope, ListingStatus
from diucs.domain.rules.network_board import (
    NetworkServiceInput,
    assemble_network_board,
    compute_network_state,
    status_inputs,
)
from diucs.domain.rules.projection import (
    LocationInputs,
    LocationProjection,
    ServiceContactInputs,
    ServiceProjection,
    build_capacity_projection,
    build_criteria_projection,
    build_service_projection,
)
from tests.support.projection_samples import (
    NOW,
    REPORTED_AT,
    sample_capacity_projection,
    sample_policy,
    sample_profile,
    sample_report,
    sample_service_projection,
)

BOTH = frozenset({GrantScope.DIRECTORY, GrantScope.CAPACITY})


def test_a_district_that_is_not_upper_case_is_refused_on_the_location() -> None:
    with pytest.raises(ValidationFailed):
        LocationProjection("UCR West base", "dt4", None, None, None)
    with pytest.raises(ValidationFailed):
        LocationProjection("UCR West base", 4, None, None, None)  # type: ignore[arg-type]


def test_a_location_that_is_not_a_location_projection_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        replace(sample_service_projection(), location="UCR West base")  # type: ignore[arg-type]


def test_no_postcode_gives_no_district() -> None:
    location = LocationInputs("UCR West base", None, None, None, None)

    dto = sample_service_projection(location=location)

    assert dto.location is not None
    assert dto.location.postal_district is None


def test_a_postcode_that_is_not_text_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        sample_service_projection(location=LocationInputs("x", 5, None, None, None))  # type: ignore[arg-type]


def test_a_location_input_that_is_not_one_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        sample_service_projection(location={"name": "x"})


@pytest.mark.parametrize("bad", [None, "svc", {"id": "svc"}])
def test_builders_refuse_a_source_that_is_not_the_right_record(bad: Any) -> None:
    with pytest.raises(ValidationFailed):
        build_service_projection(bad, source_version=1, location=None, contact=None)
    with pytest.raises(ValidationFailed):
        build_capacity_projection(
            bad,
            None,
            confirmed_since=0,
            policy=sample_policy(),
            source_version=1,
            valid_until=None,
        )
    with pytest.raises(ValidationFailed):
        build_criteria_projection(bad)


def test_a_contact_that_is_not_contact_inputs_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        build_service_projection(
            sample_profile(),
            source_version=1,
            location=None,
            contact=("Duty desk", "0300"),  # type: ignore[arg-type]
        )
    assert ServiceContactInputs("a", "b").label == "a"


def test_a_report_that_is_not_a_report_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        build_capacity_projection(
            sample_profile(),
            {"value": 3},  # type: ignore[arg-type]
            confirmed_since=0,
            policy=sample_policy(),
            source_version=1,
            valid_until=None,
        )


def test_the_status_helpers_refuse_what_is_not_a_projection() -> None:
    service = sample_service_projection()
    with pytest.raises(ValidationFailed):
        status_inputs("capacity", service)  # type: ignore[arg-type]
    with pytest.raises(ValidationFailed):
        status_inputs(sample_capacity_projection(), "service")  # type: ignore[arg-type]
    with pytest.raises(ValidationFailed):
        compute_network_state("inputs", NOW)  # type: ignore[arg-type]
    with pytest.raises(ValidationFailed):
        compute_network_state(
            status_inputs(sample_capacity_projection(), service), NOW.replace(tzinfo=None)
        )


def test_a_network_input_with_the_wrong_kind_of_part_is_refused() -> None:
    good = NetworkServiceInput(
        "row-1",
        "Org One",
        sample_service_projection(),
        sample_capacity_projection(),
        ListingStatus.ADMITTED,
        BOTH,
    )

    with pytest.raises(ValidationFailed):
        replace(good, service="service")  # type: ignore[arg-type]
    with pytest.raises(ValidationFailed):
        replace(good, capacity="capacity")  # type: ignore[arg-type]
    other = sample_capacity_projection(profile=sample_profile(id="svc-2"), latest=None)
    with pytest.raises(ValidationFailed):
        replace(good, capacity=other)


def test_a_report_dated_after_the_read_is_never_shown_as_a_figure() -> None:
    """Clock skew between a member and the platform: the row reads Not updated."""
    future = sample_report(effective_at=NOW + timedelta(hours=1))
    capacity = sample_capacity_projection(latest=future)
    item = NetworkServiceInput(
        "row-1", "Org One", sample_service_projection(), capacity, ListingStatus.ADMITTED, BOTH
    )

    (entry,) = assemble_network_board([item], NOW, watch_from=3, high_from=5).entries

    assert entry.status is not None
    assert entry.status.value == "not-updated"
    assert (entry.effective_available, entry.used, entry.reported_at) == (None, None, None)
    assert REPORTED_AT < NOW


def test_the_scan_refuses_a_value_that_contains_itself() -> None:
    cyclic: dict[str, Any] = {}
    cyclic["a"] = cyclic

    with pytest.raises(ValidationFailed):
        find_forbidden_keys(cyclic)
    with pytest.raises(ValidationFailed):
        scan_value(cyclic)


def test_a_service_with_a_wrong_hour_record_is_refused() -> None:
    dto = sample_service_projection()

    with pytest.raises(ValidationFailed):
        replace(dto, opening_hours=("0|all-day",))  # type: ignore[arg-type]
    assert isinstance(dto, ServiceProjection)
