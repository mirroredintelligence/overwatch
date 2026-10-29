"""FHIR profile validator (R14): structure from fhir.resources.R4B, then one rule per profile.

The profiles are published as StructureDefinition files in backend/profiles/ and their URLs are
`{BASE_URL}StructureDefinition/<Name>`. Two layers check a resource:

1. Structure: fhir.resources.R4B parses the resource. Each parse error becomes an issue at the
   element it names. A profile whose resource is not valid R4B (the criteria Basic, whose elements
   the repository stores as properties, DEC-001) skips this layer and runs only its rules.
2. Profile rules: one function per profile, kept in step with the file of the same name by a test.

An empty list means valid. Every issue names an element path and a fixed message. No issue quotes a
value: a value can be a postcode, a name or a figure about a patient.

The rules are plain Python, so the HL7 validator can replace this later behind the same port
(FhirValidator). Not validated against the FHIR ShEx schemas or the HL7 profile engine. UK Core
derivation is out of scope (needs a decision first).
"""

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final

from fhir.resources.R4B import get_fhir_model_class
from pydantic import ValidationError

from diucs.application.ports.outbound.terminology import ValidationIssue, profile_url
from diucs.domain.codes import (
    BASE_URL,
    AgeBand,
    CriteriaStatus,
    Measure,
    NeedCategory,
    ReportSource,
    code_system_url,
    parse_code,
)
from diucs.domain.errors import ValidationFailed

UCUM_SYSTEM: Final = "http://unitsofmeasure.org"
AGE_BAND_EXTENSION: Final = f"{BASE_URL}Extension/age-band"
CASE_STUB_TAG: Final = "pseudonymised-case-stub"
BOOKING_CODE: Final = "booking-request"
_REFERENCE: Final = re.compile(r"[A-Za-z]+/[A-Za-z0-9\-.]{1,64}")

ProfileCheck = Callable[[dict[str, Any]], list[ValidationIssue]]


def _issue(path: str, message: str, code: str = "invalid") -> ValidationIssue:
    return ValidationIssue(severity="error", code=code, path=path, message=message)


def _codings(concept: Any, system: str) -> list[str]:
    """The codes of a CodeableConcept's codings in one code system (a bad shape gives none)."""
    if not isinstance(concept, dict) or not isinstance(concept.get("coding"), list):
        return []
    return [
        coding["code"]
        for coding in concept["coding"]
        if isinstance(coding, dict)
        and coding.get("system") == system
        and isinstance(coding.get("code"), str)
    ]


def _one_code(concept: Any, system: str, enum_cls: type[StrEnum]) -> bool:
    codes = _codings(concept, system)
    if len(codes) != 1:
        return False
    try:
        parse_code(enum_cls, codes[0])
    except ValidationFailed:
        return False
    return True


def _one_reference(value: Any, target: str) -> bool:
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        return False
    reference = value[0].get("reference")
    return (
        isinstance(reference, str)
        and reference.startswith(f"{target}/")
        and _REFERENCE.fullmatch(reference) is not None
    )


def _whole_at_least(value: Any, minimum: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _capacity(resource: dict[str, Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if resource.get("status") != "final":
        issues.append(_issue("Observation.status", "must be final"))
    if not _one_code(resource.get("code"), code_system_url("capacity-measure"), Measure):
        issues.append(_issue("Observation.code", "must be one capacity measure"))
    if not _one_reference(resource.get("focus"), "HealthcareService"):
        issues.append(_issue("Observation.focus", "must name the one service reported on"))
    quantity = resource.get("valueQuantity")
    if not isinstance(quantity, dict):
        issues.append(_issue("Observation.valueQuantity", "is required"))
    else:
        value = quantity.get("value")
        if not _whole_at_least(value, 0):
            issues.append(
                _issue("Observation.valueQuantity.value", "must be a whole number, zero or more")
            )
        if quantity.get("system") != UCUM_SYSTEM:
            issues.append(_issue("Observation.valueQuantity.system", "must be the UCUM system"))
        unit = quantity.get("code")
        if not isinstance(unit, str) or not unit:
            issues.append(_issue("Observation.valueQuantity.code", "needs a UCUM annotation"))
    if not _one_code(resource.get("method"), code_system_url("report-source"), ReportSource):
        issues.append(_issue("Observation.method", "must be one report source"))
    if not isinstance(resource.get("effectiveDateTime"), str):
        issues.append(_issue("Observation.effectiveDateTime", "is required"))
    return issues


_FORBIDDEN_IN_STUB: Final[Mapping[str, str]] = MappingProxyType(
    {
        "name": "No patient names are stored",
        "identifier": "No patient identifiers are stored",
        "birthDate": "No dates of birth are stored",
        "telecom": "No contact details are stored",
    }
)


def _case_stub(resource: dict[str, Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for element, message in _FORBIDDEN_IN_STUB.items():
        if resource.get(element) not in (None, [], ""):
            issues.append(_issue(f"Patient.{element}", message))
    meta = resource.get("meta")
    tags = meta.get("tag") if isinstance(meta, dict) else None
    tag_codes = [t.get("code") for t in tags or [] if isinstance(t, dict)]
    if CASE_STUB_TAG not in tag_codes:
        issues.append(_issue("Patient.meta.tag", f"must carry the {CASE_STUB_TAG} tag"))
    bands = [
        e
        for e in resource.get("extension") or []
        if isinstance(e, dict) and e.get("url") == AGE_BAND_EXTENSION
    ]
    if len(bands) != 1:
        issues.append(_issue("Patient.extension", "needs exactly one age band"))
    elif not any(bands[0].get("valueCode") == band.value for band in AgeBand):
        issues.append(_issue("Patient.extension.valueCode", "must be an age band"))
    return issues


def _criteria(resource: dict[str, Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not _one_reference(resource.get("subject"), "HealthcareService"):
        issues.append(_issue("Basic.subject", "must name the one service the criteria are for"))
    status = resource.get("status")
    if not isinstance(status, str) or status not in {c.value for c in CriteriaStatus}:
        issues.append(_issue("Basic.status", "must be a criteria status"))
    age_min = resource.get("ageMin")
    if not _whole_at_least(age_min, 0):
        issues.append(_issue("Basic.ageMin", "must be a whole number, zero or more"))
    age_max = resource.get("ageMax")
    if age_max is not None and (
        not _whole_at_least(age_max, 0) or (_whole_at_least(age_min, 0) and age_max < age_min)
    ):
        issues.append(_issue("Basic.ageMax", "must be a whole number not below the minimum"))
    version = resource.get("version")
    if not _whole_at_least(version, 1):
        issues.append(_issue("Basic.version", "must be a whole number from 1"))
    if not isinstance(resource.get("reviewBy"), str):
        issues.append(_issue("Basic.reviewBy", "is required"))
    for element, system, enum_cls in (
        ("acceptsNeed", code_system_url("need-category"), NeedCategory),
        ("excludesNeed", code_system_url("need-category"), NeedCategory),
    ):
        for concept in resource.get(element) or []:
            if not _one_code(concept, system, enum_cls):
                issues.append(_issue(f"Basic.{element}", "must be need categories"))
                break
    return issues


def _booking(resource: dict[str, Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if resource.get("intent") != "order":
        issues.append(_issue("Task.intent", "must be order"))
    concept = resource.get("code")
    codings = concept.get("coding") if isinstance(concept, dict) else None
    codes = [c.get("code") for c in codings or [] if isinstance(c, dict)]
    if BOOKING_CODE not in codes:
        issues.append(_issue("Task.code", "must be the booking-request code"))
    if not _one_reference(resource.get("owner"), "HealthcareService"):
        issues.append(_issue("Task.owner", "must name the service asked"))
    if not _one_reference(resource.get("focus"), "ServiceRequest"):
        issues.append(_issue("Task.focus", "must name the case"))
    return issues


def _service(resource: dict[str, Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    name = resource.get("name")
    if not isinstance(name, str) or not name:
        issues.append(_issue("HealthcareService.name", "is required"))
    if not isinstance(resource.get("active"), bool):
        issues.append(_issue("HealthcareService.active", "must be true or false"))
    category = resource.get("category")
    if not isinstance(category, list) or not category:
        issues.append(_issue("HealthcareService.category", "is required"))
    if not _one_reference(resource.get("providedBy"), "Organization"):
        issues.append(_issue("HealthcareService.providedBy", "must name the organisation"))
    return issues


@dataclass(frozen=True, slots=True)
class _Profile:
    name: str
    resource_type: str
    structural: bool
    check: ProfileCheck


PROFILES: Final[tuple[_Profile, ...]] = (
    _Profile("DiucsCapacityReport", "Observation", True, _capacity),
    _Profile("DiucsPatientCaseStub", "Patient", True, _case_stub),
    _Profile("DiucsServiceCriteria", "Basic", False, _criteria),
    _Profile("DiucsBookingRequest", "Task", True, _booking),
    _Profile("DiucsHealthcareService", "HealthcareService", True, _service),
)
PROFILE_NAMES: Final[tuple[str, ...]] = tuple(profile.name for profile in PROFILES)
_BY_URL: Final[Mapping[str, _Profile]] = MappingProxyType(
    {profile_url(profile.name): profile for profile in PROFILES}
)


def _structure(resource: dict[str, Any], resource_type: str) -> list[ValidationIssue]:
    """The R4B parse of the resource. Each error names its element by path and gives a fixed
    message, never the input value (pydantic's messages can quote it)."""
    try:
        model = get_fhir_model_class(resource_type)
    except LookupError:
        return [_issue("resourceType", "is not a FHIR R4B resource type", "structure")]
    try:
        model.model_validate(resource)
    except ValidationError as exc:
        return [
            _issue(
                ".".join([resource_type, *(str(part) for part in error["loc"])]),
                "is not valid FHIR R4B",
                "structure",
            )
            for error in exc.errors()
        ]
    return []


class ProfileValidator:
    """The FhirValidator of the FHIR API (R14): structure, then the profile's rules."""

    async def validate(self, resource: dict[str, Any], profile: str) -> list[ValidationIssue]:
        published = _BY_URL.get(profile)
        if published is None:
            return [_issue("", "is not a profile this server publishes", "not-supported")]
        if (
            not isinstance(resource, dict)
            or resource.get("resourceType") != published.resource_type
        ):
            return [_issue("resourceType", f"must be {published.resource_type} for this profile")]
        if published.structural:
            structural = _structure(resource, published.resource_type)
            if structural:
                return structural
        return published.check(resource)
