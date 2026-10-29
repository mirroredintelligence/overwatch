"""Notification consent (I14). Stub: the behaviour is written in the implement step."""

from datetime import datetime
from typing import Any, Final

CONSENT_CATEGORY_CODE: Final = "notification"
CONSENT_WORDING_EXTENSION: Final = "https://diucs.example/StructureDefinition/consent-wording-version"


def consent_id(device_id: str) -> str:
    raise NotImplementedError


def consent_resource(
    practitioner_id: str, device_id: str, wording_version: str, status: str, at: datetime
) -> dict[str, Any]:
    raise NotImplementedError
