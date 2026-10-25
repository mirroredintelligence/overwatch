"""Fakes for the terminology and validator ports (P11). External providers only (DEC-002, DEC-004).

FixedTerminology answers from fixed tables. PassThroughValidator reports every resource as valid.
RecordingValidator returns preset issues and keeps each call, so a test can see what was asked.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from diucs.application.ports.outbound.terminology import OdsRecord, ValidationIssue


class FixedTerminology:
    def __init__(
        self,
        ods: Mapping[str, OdsRecord],
        displays: Mapping[tuple[str, str], str],
    ) -> None:
        raise NotImplementedError

    async def ods_lookup(self, code: str) -> OdsRecord | None:
        raise NotImplementedError

    async def display(self, system: str, code: str) -> str | None:
        raise NotImplementedError


class PassThroughValidator:
    async def validate(self, resource: dict[str, Any], profile: str) -> list[ValidationIssue]:
        raise NotImplementedError


class RecordingValidator:
    def __init__(self, issues: Sequence[ValidationIssue]) -> None:
        raise NotImplementedError

    @property
    def calls(self) -> list[tuple[dict[str, Any], str]]:
        raise NotImplementedError

    async def validate(self, resource: dict[str, Any], profile: str) -> list[ValidationIssue]:
        raise NotImplementedError
