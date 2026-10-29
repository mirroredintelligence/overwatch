"""Outbound ports for terminology and FHIR validation (P11).

The ODS directory, the terminology server and the FHIR validator are external providers, so each
has a fake in diucs.adapters.testing (DEC-002, DEC-004). The real adapters come later (I12, R14).

An empty list from FhirValidator.validate means valid. Any issue, of any severity, is returned.
"""

from dataclasses import dataclass
from typing import Any, Literal, Protocol, get_args

from diucs.domain.errors import ValidationFailed

Severity = Literal["fatal", "error", "warning", "information"]
"""The FHIR issue severities (OperationOutcome.issue.severity)."""

_SEVERITIES: frozenset[str] = frozenset(get_args(Severity))


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

    def __post_init__(self) -> None:
        if self.severity not in _SEVERITIES:
            raise ValidationFailed("severity", "must be a FHIR issue severity")


class Terminology(Protocol):
    async def ods_lookup(self, code: str) -> OdsRecord | None: ...

    async def display(self, system: str, code: str) -> str | None: ...

    async def search_pathways_dx(self, text: str, limit: int = 20) -> list[tuple[str, str]]:
        """The Pathways Dx codes (code, display) whose code or display contains `text`, in code
        order, at most `limit`. Text under two characters, once trimmed, finds nothing (R16)."""
        ...


class FhirValidator(Protocol):
    async def validate(self, resource: dict[str, Any], profile: str) -> list[ValidationIssue]: ...
