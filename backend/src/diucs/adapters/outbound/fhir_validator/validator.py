"""FHIR profile validator (R14). Stub for the red commit (DEC-010)."""

from typing import Any, Final

from diucs.application.ports.outbound.terminology import ValidationIssue
from diucs.domain.codes import BASE_URL

PROFILE_NAMES: Final[tuple[str, ...]] = ()


def profile_url(name: str) -> str:
    """The canonical URL of a profile: `{BASE_URL}StructureDefinition/<Name>`."""
    return f"{BASE_URL}StructureDefinition/{name}"


class ProfileValidator:
    async def validate(self, resource: dict[str, Any], profile: str) -> list[ValidationIssue]:
        raise NotImplementedError("R14: the profile validator is not built yet")
