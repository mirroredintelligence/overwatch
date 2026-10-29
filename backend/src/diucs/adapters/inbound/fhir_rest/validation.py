"""The profile check of a FHIR request body (R14): `validated_body`, and the OperationOutcome of a
body that does not conform.

A write is checked against its profile before it reaches a use case: a body that breaks the profile
is refused with every problem, each at its element. The checks read nothing from the store, so the
refusal never depends on what exists. This module imports no outbound adapter: the validator is the
container's `validator` (the FhirValidator port).
"""

import json
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from fastapi import Request

from diucs.application.ports.outbound.terminology import ValidationIssue
from diucs.domain.errors import ValidationFailed


class ProfileRejected(Exception):
    """A body that breaks its profile. Carries every issue, each with its element path."""

    def __init__(self, issues: Sequence[ValidationIssue]) -> None:
        super().__init__("the body does not conform to its profile")
        self.issues: tuple[ValidationIssue, ...] = tuple(issues)


def issue_outcome(issues: Sequence[ValidationIssue]) -> dict[str, Any]:
    """The OperationOutcome for a list of issues. An issue with no element path has no
    expression."""
    entries: list[dict[str, Any]] = []
    for issue in issues:
        entry: dict[str, Any] = {
            "severity": issue.severity,
            "code": issue.code,
            "diagnostics": issue.message,
        }
        if issue.path:
            entry["expression"] = [issue.path]
        entries.append(entry)
    return {"resourceType": "OperationOutcome", "issue": entries}


async def json_body(request: Request, element: str) -> Any:
    """The JSON body, or ValidationFailed naming the element. The body is read once and cached."""
    try:
        return json.loads(await request.body())
    except ValueError:
        raise ValidationFailed(element, "the body is not valid JSON") from None


def validated_body(profile: str, element: str) -> Callable[[Request], Awaitable[dict[str, Any]]]:
    """A dependency that refuses a body that does not conform to `profile` (R14). `element` names
    the body in the refusal of a body that is not a JSON object."""

    async def dependency(request: Request) -> dict[str, Any]:
        body = await json_body(request, element)
        if not isinstance(body, dict):
            raise ValidationFailed(element, "the body must be a JSON object")
        issues = await request.app.state.container.validator.validate(body, profile)
        if issues:
            raise ProfileRejected(issues)
        return body

    return dependency
