"""An invitation as a FHIR Task with code invite-reporter (U24, fhir-data-model.md "Invitation").

The Task focuses the service, is requested by the shift lead's post, is owned by the invitee
practitioner and is part of the registration Task it opens. `restriction.period` runs from the
latest send to the expiry (48 hours later). `description` holds the role label the lead typed. The
link token is held by the link adapter as a hash and never appears here, and neither does the
phone number (the protected contact store keeps it).

Pure: no I/O. The resource goes through the resource store like any other, so the graph holds the
decomposed properties and relationships and no JSON (DEC-001).
"""

from datetime import UTC, datetime
from typing import Any, Final

from diucs.domain.codes import code_system_url
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.registration import Invitation

TASK: Final = "Task"
INVITE_REPORTER: Final = "invite-reporter"
TASK_CODE_SYSTEM: Final = code_system_url("task-code")
_SERVICE: Final = "HealthcareService"
_ROLE: Final = "PractitionerRole"
_PRACTITIONER: Final = "Practitioner"


def _iso(value: datetime) -> str:
    """UTC, with Z."""
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _instant(field: str, text: Any) -> datetime:
    if not isinstance(text, str):
        raise ValidationFailed(field, "must be a FHIR datetime")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise ValidationFailed(field, "not a FHIR datetime") from None
    if parsed.tzinfo is None:
        raise ValidationFailed(field, "must carry a UTC offset")
    return parsed.astimezone(UTC)


def _target(value: Any, element: str, resource_type: str) -> str:
    reference = value.get("reference") if isinstance(value, dict) else None
    prefix = f"{resource_type}/"
    if (
        not isinstance(reference, str)
        or not reference.startswith(prefix)
        or len(reference) == len(prefix)
    ):
        raise ValidationFailed(element, f"must reference a {resource_type}")
    return reference[len(prefix) :]


def is_invitation(resource: dict[str, Any]) -> bool:
    """Whether a Task carries the invite-reporter code and no other."""
    code = resource.get("code")
    codings = code.get("coding") if isinstance(code, dict) else None
    if not isinstance(codings, list) or len(codings) != 1 or not isinstance(codings[0], dict):
        return False
    return (
        codings[0].get("system") == TASK_CODE_SYSTEM and codings[0].get("code") == INVITE_REPORTER
    )


def invitation_to_fhir(invitation: Invitation) -> dict[str, Any]:
    """The Task for an invitation. No meta: the store sets it."""
    return {
        "resourceType": TASK,
        "id": invitation.id,
        "status": "requested",
        "intent": "order",
        "code": {"coding": [{"system": TASK_CODE_SYSTEM, "code": INVITE_REPORTER}]},
        "description": invitation.role_label,
        "authoredOn": _iso(invitation.created_at),
        "lastModified": _iso(invitation.sent_at),
        "focus": {"reference": f"{_SERVICE}/{invitation.service_id}"},
        "requester": {"reference": f"{_ROLE}/{invitation.requester_role_id}"},
        "owner": {"reference": f"{_PRACTITIONER}/{invitation.invitee_id}"},
        "partOf": [{"reference": f"{TASK}/{invitation.registration_id}"}],
        "restriction": {
            "period": {"start": _iso(invitation.sent_at), "end": _iso(invitation.expires_at)}
        },
    }


def invitation_from_fhir(resource: dict[str, Any]) -> Invitation:
    """The invitation for a Task. Refuses a Task that is not an invitation, a missing element and a
    reference to the wrong kind of resource."""
    if not is_invitation(resource):
        raise ValidationFailed("code", "not an invitation task")
    part_of = resource.get("partOf")
    if not isinstance(part_of, list) or len(part_of) != 1:
        raise ValidationFailed("partOf", "must name the registration")
    restriction = resource.get("restriction")
    period = restriction.get("period") if isinstance(restriction, dict) else None
    if not isinstance(period, dict):
        raise ValidationFailed("restriction", "must carry the period of the invitation")
    return Invitation(
        id=str(resource["id"]),
        service_id=_target(resource.get("focus"), "focus", _SERVICE),
        registration_id=_target(part_of[0], "partOf", TASK),
        requester_role_id=_target(resource.get("requester"), "requester", _ROLE),
        invitee_id=_target(resource.get("owner"), "owner", _PRACTITIONER),
        role_label=str(resource.get("description", "")),
        created_at=_instant("authoredOn", resource.get("authoredOn")),
        sent_at=_instant("restriction.period.start", period.get("start")),
        expires_at=_instant("restriction.period.end", period.get("end")),
    )
