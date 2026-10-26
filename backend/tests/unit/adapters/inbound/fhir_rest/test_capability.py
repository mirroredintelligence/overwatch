"""register_resource refuses bad input (R01): no database, no HTTP."""

import pytest

from diucs.adapters.inbound.fhir_rest import capability


@pytest.fixture
def empty_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(capability, "_RESOURCES", {})


@pytest.mark.parametrize(
    ("resource_type", "interactions"),
    [
        ("HealthcareService", ["delete-everything"]),
        ("", ["read"]),
    ],
)
def test_a_resource_with_an_unknown_interaction_or_no_type_is_refused(
    empty_registry: None, resource_type: str, interactions: list[str]
) -> None:
    with pytest.raises(ValueError):
        capability.register_resource(resource_type, interactions, [])


def test_a_resource_type_cannot_be_registered_twice(empty_registry: None) -> None:
    capability.register_resource("HealthcareService", ["read"], [])

    with pytest.raises(ValueError):
        capability.register_resource("HealthcareService", ["read", "create"], [])
