"""Outbound ports for terminology and FHIR validation (P11).

The ODS directory, the terminology server and the FHIR validator are external providers, so each
has a fake in diucs.adapters.testing (DEC-002, DEC-004). The real adapters come later (I12, R14).

An empty list from FhirValidator.validate means valid. Any issue, of any severity, is returned.
"""

from dataclasses import dataclass
from typing import Any, Literal, Protocol

Severity = Literal["fatal", "error", "warning", "information"]
"""The FHIR issue severities (OperationOutcome.issue.severity)."""


@dataclass(frozen=True, slots=True)
class OdsRecord:
    code: str
    name: str
    active: bool
    org_type: str
    postcode: str | None


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    severity: Severity
    code: str
    path: str
    message: str


class Terminology(Protocol):
    async def ods_lookup(self, code: str) -> OdsRecord | None: ...

    async def display(self, system: str, code: str) -> str | None: ...


class FhirValidator(Protocol):
    async def validate(self, resource: dict[str, Any], profile: str) -> list[ValidationIssue]: ...
