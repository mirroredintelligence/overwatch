"""The pure parts of FHIR auth (R02): claims to Actor, service and patient scope, and projections.

The HTTP cases (401, 404 bodies, routes) are in tests/integration/adapters/inbound/fhir_rest.
Sample identifiers only: prac-1, svc-1, dev-1, pat-1 and req-1.
"""

from datetime import UTC, datetime

import pytest
from fhir.resources.R4B.patient import Patient
from fhir.resources.R4B.task import Task

from diucs.adapters.inbound.fhir_rest.auth import (
    PATIENT_ROLES,
    PROJECTIONS,
    ProjectionRegistry,
    actor_from_claims,
    ensure_can_act_for,
    ensure_patient_access,
)
from diucs.application.actor import Actor
from diucs.domain.codes import Role
from diucs.domain.errors import NotAllowed
from diucs.domain.rules.bff_token import BffClaims

EXPIRES = datetime(2026, 10, 24, 13, 12, tzinfo=UTC)
REDACTED_SYSTEM = "http://terminology.hl7.org/CodeSystem/v3-ObservationValue"


def claims(
    role: Role, sub: str, services: frozenset[str] = frozenset({"svc-1"}), device: str | None = None
) -> BffClaims:
    return BffClaims(sub=sub, role=role, services=services, expires_at=EXPIRES, device=device)


def actor(role: Role, services: frozenset[str] = frozenset({"svc-1"})) -> Actor:
    return Actor(
        role=role,
        practitioner_id="prac-1",
        device_id=None,
        channel="api",
        service_ids=services,
    )


def test_a_reporter_claim_gives_its_practitioner_and_services() -> None:
    result = actor_from_claims(claims(Role.REPORTER, "prac-1"))

    assert result == Actor(
        role=Role.REPORTER,
        practitioner_id="prac-1",
        device_id=None,
        channel="api",
        service_ids=frozenset({"svc-1"}),
    )


def test_a_wall_claim_sets_the_device_and_not_the_practitioner() -> None:
    result = actor_from_claims(claims(Role.WALL, "dev-1", frozenset()))

    assert result.practitioner_id is None
    assert result.device_id == "dev-1"
    assert result.role is Role.WALL


def test_a_device_claim_is_kept_for_a_person() -> None:
    result = actor_from_claims(claims(Role.REPORTER, "prac-1", device="phone-1"))

    assert result.device_id == "phone-1"
    assert result.practitioner_id == "prac-1"


@pytest.mark.parametrize(
    ("role", "services", "service_id", "allowed"),
    [
        pytest.param(Role.REPORTER, frozenset({"svc-1"}), "svc-1", True, id="reporter-own"),
        pytest.param(Role.REPORTER, frozenset({"svc-1"}), "svc-2", False, id="reporter-other"),
        pytest.param(Role.REPORTER, frozenset(), "svc-1", False, id="reporter-no-scope"),
        pytest.param(Role.LEAD, frozenset(), "svc-2", True, id="lead-anywhere"),
        pytest.param(Role.ADVISOR, frozenset(), "svc-2", True, id="advisor-anywhere"),
        pytest.param(Role.CLINICAL, frozenset(), "svc-2", True, id="clinical-anywhere"),
        pytest.param(Role.AUDIT, frozenset(), "svc-2", True, id="audit-anywhere"),
        pytest.param(Role.OWNER, frozenset(), "svc-2", False, id="owner-not-in-list"),
        pytest.param(Role.EXEC, frozenset(), "svc-2", False, id="exec-not-in-list"),
        pytest.param(Role.WALL, frozenset(), "svc-2", False, id="wall-not-in-list"),
    ],
)
def test_acting_for_a_service_needs_scope_or_a_wide_role(
    role: Role, services: frozenset[str], service_id: str, allowed: bool
) -> None:
    subject = actor(role, services)

    if allowed:
        ensure_can_act_for(subject, service_id)
    else:
        with pytest.raises(NotAllowed):
            ensure_can_act_for(subject, service_id)


def test_patient_roles_are_advisor_and_clinical() -> None:
    assert frozenset({Role.ADVISOR, Role.CLINICAL}) == PATIENT_ROLES


@pytest.mark.parametrize("role", [Role.EXEC, Role.WALL, Role.REPORTER])
def test_patient_level_access_is_refused_to_the_roles_named(role: Role) -> None:
    with pytest.raises(NotAllowed):
        ensure_patient_access(actor(role))


@pytest.mark.parametrize("role", [Role.ADVISOR, Role.CLINICAL])
def test_patient_level_access_is_allowed_to_advisor_and_clinical(role: Role) -> None:
    ensure_patient_access(actor(role))


def _booking_task() -> Task:
    return Task.model_validate(
        {
            "status": "requested",
            "intent": "order",
            "focus": {"reference": "ServiceRequest/req-1"},
            "for": {"reference": "Patient/pat-1"},
        }
    )


def test_a_reporter_sees_a_booking_task_without_its_case_and_with_the_label() -> None:
    task = _booking_task()

    projected = PROJECTIONS.project(task, actor(Role.REPORTER))

    assert projected.focus is None
    assert projected.for_fhir is None
    assert projected.meta is not None
    assert projected.meta.security is not None
    assert [(c.system, c.code) for c in projected.meta.security] == [(REDACTED_SYSTEM, "REDACTED")]


def test_projecting_does_not_change_the_resource_it_was_given() -> None:
    task = _booking_task()

    PROJECTIONS.project(task, actor(Role.REPORTER))

    assert task.focus is not None
    assert task.for_fhir is not None
    assert task.meta is None


def test_an_advisor_sees_the_booking_task_unchanged_with_no_label() -> None:
    task = _booking_task()

    projected = PROJECTIONS.project(task, actor(Role.ADVISOR))

    assert projected == task
    assert projected.meta is None or not projected.meta.security


def test_a_reporter_task_with_nothing_to_remove_gets_no_label() -> None:
    task = Task.model_validate({"status": "requested", "intent": "order"})

    projected = PROJECTIONS.project(task, actor(Role.REPORTER))

    assert projected == task
    assert projected.meta is None or not projected.meta.security


def test_a_reporter_label_keeps_a_security_label_the_task_already_has() -> None:
    task = Task.model_validate(
        {
            "status": "requested",
            "intent": "order",
            "focus": {"reference": "ServiceRequest/req-1"},
            "meta": {"security": [{"system": "urn:example:other", "code": "KEEP"}]},
        }
    )

    projected = PROJECTIONS.project(task, actor(Role.REPORTER))

    assert projected.meta is not None
    assert projected.meta.security is not None
    codes = [(c.system, c.code) for c in projected.meta.security]
    assert ("urn:example:other", "KEEP") in codes
    assert (REDACTED_SYSTEM, "REDACTED") in codes


def test_a_role_with_no_rule_for_a_resource_sees_it_unchanged() -> None:
    patient = Patient.model_validate({})

    assert PROJECTIONS.project(patient, actor(Role.REPORTER)) == patient


def test_a_second_projection_for_the_same_type_and_role_is_refused() -> None:
    registry = ProjectionRegistry()
    registry.register("Task", Role.REPORTER, lambda resource: resource)

    with pytest.raises(ValueError, match="already"):
        registry.register("Task", Role.REPORTER, lambda resource: resource)
