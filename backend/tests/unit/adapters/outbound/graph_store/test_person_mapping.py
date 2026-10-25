"""Pure mapping of people to and from FHIR (P03): person_repository.py.

The FHIR form carries no telecom and no phone hash. The phone hash and the email domain are graph
properties the repository writes beside the resource (lesson L74 and DEC-063's pattern), so they
are passed in, not read from the FHIR dict.
"""

import dataclasses
from datetime import UTC, datetime
from typing import Any

import pytest

from diucs.adapters.outbound.graph_store.mapper import from_graph, to_graph
from diucs.adapters.outbound.graph_store.person_repository import (
    practitioner_from_fhir,
    practitioner_to_fhir,
    role_from_fhir,
    role_to_fhir,
)
from diucs.domain.codes import BASE_URL, Channel, PractitionerRoleCode
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.people import Practitioner, PractitionerRole

PERSON = Practitioner(
    id="p1",
    active=True,
    display_name="Duty Manager One",
    phone_hash="h1",
    email_domain="nhs.example",
)
ROLE_EAST_COVERED = PractitionerRole(
    id="r-east",
    practitioner_id="p1",
    service_id="svc-ucr-east",
    code=PractitionerRoleCode.DUTY_MANAGER,
    active=True,
    channel=Channel.TEXT,
    period_start=datetime(2026, 10, 1, tzinfo=UTC),
    period_end=datetime(2027, 1, 1, 9, 30, tzinfo=UTC),
    covered_by_practitioner_id="p2",
    covered_until=datetime(2026, 10, 25, 19, 0, tzinfo=UTC),
)


def _all_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _all_strings(item)]
    if isinstance(value, list):
        return [text for item in value for text in _all_strings(item)]
    return []


def test_practitioner_fhir_has_no_telecom() -> None:
    assert "telecom" not in practitioner_to_fhir(PERSON)


def test_practitioner_fhir_carries_no_phone_hash_or_email_domain() -> None:
    resource = practitioner_to_fhir(PERSON)

    assert "h1" not in _all_strings(resource)
    assert "nhs.example" not in _all_strings(resource)


def test_practitioner_round_trips_through_fhir_with_its_graph_properties() -> None:
    resource = practitioner_to_fhir(PERSON)

    rebuilt = practitioner_from_fhir(resource, phone_hash="h1", email_domain="nhs.example")

    assert rebuilt == PERSON


def test_the_practitioner_fhir_is_accepted_by_the_mapper_and_rebuilt_exactly() -> None:
    resource = practitioner_to_fhir(PERSON)

    assert from_graph(to_graph(resource)) == resource


def test_a_practitioner_with_no_phone_or_email_round_trips() -> None:
    person = dataclasses.replace(PERSON, phone_hash=None, email_domain=None)

    rebuilt = practitioner_from_fhir(practitioner_to_fhir(person))

    assert rebuilt == person


def test_a_role_with_cover_and_channel_round_trips_through_fhir() -> None:
    resource = role_to_fhir(ROLE_EAST_COVERED)

    assert role_from_fhir(resource) == ROLE_EAST_COVERED


def test_the_role_fhir_is_accepted_by_the_mapper_and_rebuilt_exactly() -> None:
    resource = role_to_fhir(ROLE_EAST_COVERED)

    assert from_graph(to_graph(resource)) == resource


def test_a_role_with_no_service_no_channel_and_no_cover_round_trips() -> None:
    role = dataclasses.replace(
        ROLE_EAST_COVERED,
        service_id=None,
        channel=None,
        covered_by_practitioner_id=None,
        covered_until=None,
        period_end=None,
    )

    assert role_from_fhir(role_to_fhir(role)) == role


def test_a_role_channel_that_is_not_a_channel_code_is_refused() -> None:
    role = dataclasses.replace(
        ROLE_EAST_COVERED, channel=None, covered_by_practitioner_id=None, covered_until=None
    )
    resource = role_to_fhir(role)
    resource["extension"] = [
        {"url": f"{BASE_URL}StructureDefinition/channel", "valueString": "fax"}
    ]

    with pytest.raises(ValidationFailed):
        role_from_fhir(resource)
