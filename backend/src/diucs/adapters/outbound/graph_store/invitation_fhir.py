"""STUB (U24 red): the invitation as a FHIR Task."""

from typing import Any, Final

from diucs.domain.codes import code_system_url
from diucs.domain.model.registration import Invitation

INVITE_REPORTER: Final = "invite-reporter"
TASK_CODE_SYSTEM: Final = code_system_url("task-code")


def invitation_to_fhir(invitation: Invitation) -> dict[str, Any]:
    raise NotImplementedError


def invitation_from_fhir(resource: dict[str, Any]) -> Invitation:
    raise NotImplementedError


def is_invitation(resource: dict[str, Any]) -> bool:
    raise NotImplementedError
