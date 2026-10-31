"""Notification consent on the graph (I14): one FHIR Consent per push device, written through the
resource store (G05) inside the caller's unit of work.

The shape (R4B accepts it without a patient, DEC-340): status `active` or `inactive`; `dateTime`
the instant the person chose; `performer` the Practitioner; `sourceReference` the Device the consent
is for; `category` the DIUCS code `notification`; `scope` patient-privacy, the closest R4B scope
value; `policyRule` a coding whose code is the wording version the person saw. Nothing else: no
name, telephone, postcode or subscription text (the subscription stays on the Device, P19).

The resource id is `notif-<device id>`, so one device has one consent, replaced on each change.
"""

import re
from datetime import UTC, datetime
from typing import Any, Final

from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.application.ports.outbound.consent import NotificationConsent
from diucs.domain.errors import ValidationFailed

CONSENT: Final = "Consent"
CONSENT_CATEGORY_CODE: Final = "notification"
CONSENT_CATEGORY_SYSTEM: Final = "https://diucs.example/CodeSystem/consent-category"
CONSENT_SCOPE_CODE: Final = "patient-privacy"
CONSENT_SCOPE_SYSTEM: Final = "http://terminology.hl7.org/CodeSystem/consentscope"
CONSENT_WORDING_SYSTEM: Final = "https://diucs.example/CodeSystem/consent-wording"
ACTIVE: Final = "active"
INACTIVE: Final = "inactive"
_FHIR_ID: Final = re.compile(r"[A-Za-z0-9\-.]{1,64}")


def consent_id(device_id: str) -> str:
    """The FHIR id of a device's consent. A device id that is not a legal FHIR id is refused."""
    if not isinstance(device_id, str) or _FHIR_ID.fullmatch(device_id) is None:
        raise ValidationFailed("device_id", "is not a valid identifier")
    return f"notif-{device_id}"


def _instant_text(at: datetime) -> str:
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValidationFailed("at", "must be a timezone-aware datetime")
    return at.astimezone(UTC).isoformat().replace("+00:00", "Z")


def consent_resource(
    practitioner_id: str, device_id: str, wording_version: str, status: str, at: datetime
) -> dict[str, Any]:
    """The Consent resource for a device, as a plain dict for the resource store."""
    if status not in (ACTIVE, INACTIVE):
        raise ValidationFailed("status", "must be active or inactive")
    if not isinstance(wording_version, str) or not wording_version.strip():
        raise ValidationFailed("wording_version", "is required")
    return {
        "resourceType": CONSENT,
        "id": consent_id(device_id),
        "status": status,
        "scope": {"coding": [{"system": CONSENT_SCOPE_SYSTEM, "code": CONSENT_SCOPE_CODE}]},
        "category": [
            {"coding": [{"system": CONSENT_CATEGORY_SYSTEM, "code": CONSENT_CATEGORY_CODE}]}
        ],
        "dateTime": _instant_text(at),
        "performer": [{"reference": f"Practitioner/{practitioner_id}"}],
        "sourceReference": {"reference": f"Device/{device_id}"},
        "policyRule": {"coding": [{"system": CONSENT_WORDING_SYSTEM, "code": wording_version}]},
    }


def _wording_of(resource: dict[str, Any]) -> str:
    return str(resource["policyRule"]["coding"][0]["code"])


def _read_instant(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(UTC)
    text = str(value).replace("Z", "+00:00")
    return datetime.fromisoformat(text).astimezone(UTC)


def _practitioner_of(resource: dict[str, Any]) -> str:
    return str(resource["performer"][0]["reference"]).split("/", 1)[1]


class Neo4jNotificationConsentStore:
    """Implements NotificationConsentStore on the resource store of the caller's transaction."""

    def __init__(self, store: ResourceStore) -> None:
        self._store = store

    async def record(
        self, practitioner_id: str, device_id: str, wording_version: str, at: datetime
    ) -> None:
        await self._put(practitioner_id, device_id, wording_version, ACTIVE, at)

    async def withdraw(self, practitioner_id: str, device_id: str, at: datetime) -> None:
        current = await self._store.get(CONSENT, consent_id(device_id))
        if current is None:
            # Nothing was ever consented to, so there is nothing to withdraw.
            return
        await self._put(practitioner_id, device_id, _wording_of(current), INACTIVE, at)

    async def get(self, device_id: str) -> NotificationConsent | None:
        current = await self._store.get(CONSENT, consent_id(device_id))
        if current is None:
            return None
        return NotificationConsent(
            practitioner_id=_practitioner_of(current),
            device_id=device_id,
            wording_version=_wording_of(current),
            status=str(current["status"]),
            at=_read_instant(current["dateTime"]),
        )

    async def _put(
        self,
        practitioner_id: str,
        device_id: str,
        wording_version: str,
        status: str,
        at: datetime,
    ) -> None:
        resource = consent_resource(practitioner_id, device_id, wording_version, status, at)
        current = await self._store.get(CONSENT, consent_id(device_id))
        expected = None if current is None else str(current["meta"]["versionId"])
        await self._store.put(resource, expected)
