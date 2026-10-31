"""Outbound ports for terminology and FHIR validation (P11).

The ODS directory, the terminology server and the FHIR validator are external providers, so each
has a fake in diucs.adapters.testing (DEC-002, DEC-004). The real adapters come later (I12, R14).

An empty list from FhirValidator.validate means valid. Any issue, of any severity, is returned.
"""

from dataclasses import dataclass
from typing import Any, Literal, Protocol, get_args

from diucs.domain.codes import BASE_URL
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

    async def pathways_dx_listed(self, code: str) -> bool:
        """Is this exact code on the Pathways Dx list (H-85)? The code as the list holds it: case
        counts and nothing is trimmed. A value that is not text, and any code when the list is
        empty, is not listed, so a missing list refuses every code rather than accepting any."""
        ...


def profile_url(name: str) -> str:
    """The canonical URL of a published profile: `{BASE_URL}StructureDefinition/<Name>` (R14)."""
    return f"{BASE_URL}StructureDefinition/{name}"


class FhirValidator(Protocol):
    async def validate(self, resource: dict[str, Any], profile: str) -> list[ValidationIssue]: ...
