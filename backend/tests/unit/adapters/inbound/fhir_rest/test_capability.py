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


# KI-399: a route module adds operations to a type another module registered.

DEFINITION = "https://diucs.example/OperationDefinition/"


@pytest.fixture
def clean_operations(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(capability, "_RESOURCES", {})
    monkeypatch.setattr(capability, "_ADDED_OPERATIONS", {})


def _operations(statement: dict[str, object], resource_type: str) -> list[str]:
    from typing import Any, cast

    resources = cast(list[dict[str, Any]], statement["rest"][0]["resource"])  # type: ignore[index]
    found = [item for item in resources if item["type"] == resource_type]
    assert len(found) == 1
    return [operation["name"] for operation in found[0].get("operation", [])]


def _now() -> object:
    from datetime import UTC, datetime

    return datetime(2026, 10, 31, 9, 0, tzinfo=UTC)


def test_operations_added_after_the_type_was_registered_are_listed_after_its_own(
    clean_operations: None,
) -> None:
    capability.register_resource("HealthcareService", ["read"], [f"{DEFINITION}board"])

    capability.advertise_operations("HealthcareService", [f"{DEFINITION}filter-options"])

    statement = capability.build_capability_statement(_now())  # type: ignore[arg-type]
    assert _operations(statement, "HealthcareService") == ["board", "filter-options"]


def test_operations_added_before_the_type_was_registered_are_listed_once_it_is(
    clean_operations: None,
) -> None:
    capability.advertise_operations("HealthcareService", [f"{DEFINITION}declined"])
    capability.register_resource("HealthcareService", ["read"], [f"{DEFINITION}board"])

    statement = capability.build_capability_statement(_now())  # type: ignore[arg-type]
    assert _operations(statement, "HealthcareService") == ["board", "declined"]


def test_an_operation_is_listed_once_however_often_it_is_added(clean_operations: None) -> None:
    capability.register_resource("HealthcareService", ["read"], [f"{DEFINITION}board"])

    capability.advertise_operations("HealthcareService", [f"{DEFINITION}declined"])
    capability.advertise_operations(
        "HealthcareService", [f"{DEFINITION}declined", f"{DEFINITION}board"]
    )

    statement = capability.build_capability_statement(_now())  # type: ignore[arg-type]
    assert _operations(statement, "HealthcareService") == ["board", "declined"]


def test_operations_of_a_type_nobody_registered_are_not_advertised(clean_operations: None) -> None:
    capability.advertise_operations("Basic", [f"{DEFINITION}anything"])

    statement = capability.build_capability_statement(_now())  # type: ignore[arg-type]
    assert statement["rest"][0].get("resource", []) == []  # type: ignore[index]


def test_an_operation_that_is_not_a_canonical_url_is_refused(clean_operations: None) -> None:
    with pytest.raises(ValueError):
        capability.advertise_operations("HealthcareService", ["filter-options"])
