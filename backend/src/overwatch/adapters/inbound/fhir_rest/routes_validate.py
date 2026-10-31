"""POST /fhir/{type}/$validate: checks a resource against a published profile (R14).

The answer is an OperationOutcome with status 200 whether or not the resource conforms, as the FHIR
$validate operation returns its findings in the body. A conforming resource gets one information
issue, "Valid". The caller must be signed in (any role): the operation reads nothing from the store,
but an open validator would be an open service on the platform's own rules.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from diucs.adapters.inbound.fhir_rest import capability
from diucs.adapters.inbound.fhir_rest.auth import current_actor, ensure_screen_live
from diucs.adapters.inbound.fhir_rest.capability import FhirJSONResponse
from diucs.adapters.inbound.fhir_rest.validation import issue_outcome, json_body
from diucs.application.actor import Actor
from diucs.application.ports.outbound.terminology import ValidationIssue, profile_url
from diucs.domain.errors import ValidationFailed

router = APIRouter(prefix="/fhir")

# The profiles of the types this API serves, advertised in the CapabilityStatement (R14).
_SERVED_PROFILES: tuple[tuple[str, str], ...] = (
    ("Observation", "DiucsCapacityReport"),
    ("HealthcareService", "DiucsHealthcareService"),
)


def register_profiles() -> None:
    """Advertise the profile of each served type in the CapabilityStatement, once per process."""
    for resource_type, name in _SERVED_PROFILES:
        capability.add_supported_profile(resource_type, profile_url(name))


@router.post("/{resource_type}/$validate")
async def validate_resource(
    resource_type: str,
    profile: str,
    request: Request,
    actor: Annotated[Actor, Depends(current_actor)],
) -> FhirJSONResponse:
    await ensure_screen_live(request, actor)
    body: Any = await json_body(request, "resourceType")
    if not isinstance(body, dict) or body.get("resourceType") != resource_type:
        raise ValidationFailed("resourceType", "must match the resource type in the path")
    issues = await request.app.state.container.validator.validate(body, profile)
    if not issues:
        issues = [ValidationIssue("information", "informational", "", "Valid")]
    return FhirJSONResponse(content=issue_outcome(issues), status_code=200)
