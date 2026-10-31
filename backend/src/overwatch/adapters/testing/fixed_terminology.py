"""Fakes for the terminology and validator ports (P11). External providers only (DEC-002, DEC-004).

FixedTerminology answers from fixed tables. PassThroughValidator reports every resource as valid,
which is the documented stand-in for the FHIR validator until R14 (architecture: "Pass-through").
RecordingValidator returns preset issues and keeps each call, so a test can see what was asked.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from diucs.application.ports.outbound.terminology import OdsRecord, ValidationIssue
from diucs.domain.errors import ValidationFailed
from diucs.domain.rules.code_search import search_codes


def _ods_key(code: str) -> str:
    """ODS codes are matched without regard to case or surrounding spaces."""
    return code.strip().upper()


class FixedTerminology:
    """ODS lookups by code, and display names by (system, code). Unknown is None.

    An ODS record is returned as stored, including an inactive one; the caller checks `active`.
    Display codes are matched exactly, because FHIR codes are case-sensitive. Pathways Dx entries
    (R16) are searched as the domain rule searches them: case-insensitively, in code order.
    """

    def __init__(
        self,
        ods: Mapping[str, OdsRecord],
        displays: Mapping[tuple[str, str], str],
        pathways_dx: Sequence[tuple[str, str]] = (),
    ) -> None:
        self._ods: dict[str, OdsRecord] = {}
        for key, record in ods.items():
            if _ods_key(key) != _ods_key(record.code):
                raise ValidationFailed("code", "record is stored under another code")
            self._ods[_ods_key(key)] = record
        self._displays: dict[tuple[str, str], str] = dict(displays)
        self._pathways_dx: tuple[tuple[str, str], ...] = tuple(pathways_dx)

    async def ods_lookup(self, code: str) -> OdsRecord | None:
        return self._ods.get(_ods_key(code))

    async def display(self, system: str, code: str) -> str | None:
        return self._displays.get((system, code))

    async def search_pathways_dx(self, text: str, limit: int = 20) -> list[tuple[str, str]]:
        return search_codes(self._pathways_dx, text, limit)

    async def pathways_dx_listed(self, code: str) -> bool:
        return type(code) is str and any(code == listed for listed, _ in self._pathways_dx)


class PassThroughValidator:
    """Reports every resource as valid. A stand-in for the FHIR validator, not a validation."""

    async def validate(self, resource: dict[str, Any], profile: str) -> list[ValidationIssue]:
        return []


class RecordingValidator:
    """Returns the same preset issues on every call and keeps a copy of each call's arguments."""

    def __init__(self, issues: Sequence[ValidationIssue]) -> None:
        self._issues: tuple[ValidationIssue, ...] = tuple(issues)
        self._calls: list[tuple[dict[str, Any], str]] = []

    @property
    def calls(self) -> list[tuple[dict[str, Any], str]]:
        return list(self._calls)

    async def validate(self, resource: dict[str, Any], profile: str) -> list[ValidationIssue]:
        self._calls.append((dict(resource), profile))
        return list(self._issues)
