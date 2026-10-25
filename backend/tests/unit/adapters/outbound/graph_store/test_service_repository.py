"""Pure tests for the service profile mapping (P01).

ServiceProfile <-> FHIR HealthcareService. A profile must survive the mapping unchanged, and a
value the mapping cannot hold exactly is refused, not stored. All values are synthetic.
"""

from dataclasses import replace
from datetime import time

import pytest

from diucs.adapters.outbound.graph_store.service_repository import (
    profile_from_fhir,
    profile_to_fhir,
)
from diucs.domain.codes import BASE_URL, Cadence, Channel, Measure, ServiceCategory
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.service import AvailableTime, ServiceProfile

UCR_WEST = ServiceProfile(
    id="svc-ucr-west",
    name="UCR West",
    category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
    measure=Measure.REFERRALS_ACCEPTABLE,
    unit_label="referrals",
    established_capacity=8,
    can_exceed_established=False,
    usual_range=(0, 8),
    cadence=Cadence.EVERY_2_HRS,
    available_times=(AvailableTime.weekdays(time(8, 0), time(20, 0)),),
    channel=Channel.TEXT,
    limited_level_percent=80,
)


def test_ucr_west_round_trips_through_fhir() -> None:
    assert profile_from_fhir(profile_to_fhir(UCR_WEST)) == UCR_WEST


def test_ucr_west_is_written_with_the_fhir_names() -> None:
    resource = profile_to_fhir(UCR_WEST)

    assert resource["resourceType"] == "HealthcareService"
    assert resource["id"] == "svc-ucr-west"
    assert resource["name"] == "UCR West"
    assert resource["active"] is True
    assert resource["availableTime"] == [
        {
            "daysOfWeek": ["mon", "tue", "wed", "thu", "fri"],
            "allDay": False,
            "availableStartTime": "08:00:00",
            "availableEndTime": "20:00:00",
        }
    ]
    established = f"{BASE_URL}StructureDefinition/establishedCapacity"
    assert {"url": established, "valueInteger": 8} in resource["extension"]


def test_the_category_is_a_concept_from_the_service_category_system() -> None:
    assert profile_to_fhir(UCR_WEST)["category"] == {
        "coding": [
            {
                "system": f"{BASE_URL}CodeSystem/service-category",
                "code": "urgent-community-response",
                "display": "Urgent community response",
            }
        ]
    }


@pytest.mark.parametrize(
    "available_times",
    [
        (AvailableTime.every_day_all_day(),),
        (AvailableTime.every_day(time(20, 0), time(8, 0)),),
        (
            AvailableTime.weekdays(time(8, 0), time(12, 0)),
            AvailableTime.weekdays(time(12, 0), time(20, 0)),
        ),
        (AvailableTime.every_day(time(8, 0), time(12, 0)), AvailableTime.every_day_all_day()),
    ],
    ids=["all-day", "overnight", "adjacent-windows", "timed-then-all-day"],
)
def test_every_window_shape_round_trips(available_times: tuple[AvailableTime, ...]) -> None:
    profile = replace(UCR_WEST, available_times=available_times)

    assert profile_from_fhir(profile_to_fhir(profile)) == profile


def test_a_comment_round_trips_and_an_empty_one_is_left_out() -> None:
    with_comment = replace(UCR_WEST, comment="Phone before 16:00")

    assert profile_from_fhir(profile_to_fhir(with_comment)) == with_comment
    assert "comment" not in profile_to_fhir(UCR_WEST)


def test_suspended_is_not_stored_and_reads_back_false() -> None:
    suspended = replace(UCR_WEST, suspended=True)

    resource = profile_to_fhir(suspended)

    assert "suspended" not in resource
    assert profile_from_fhir(resource).suspended is False


def test_a_category_code_from_another_code_system_is_refused() -> None:
    resource = profile_to_fhir(UCR_WEST)
    resource["category"]["coding"][0]["system"] = f"{BASE_URL}CodeSystem/referrer-type"

    with pytest.raises(ValidationFailed):
        profile_from_fhir(resource)
