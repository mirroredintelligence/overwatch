"""Outbound port: notification consent (I14).

A person's permission to receive Web Push is recorded per device, next to the push subscription
(P19) and in the same unit of work as it. The consent is a FHIR Consent resource written through the
resource store (G05): R4B accepts it without a patient, performed by the practitioner. Adapter:
Neo4jNotificationConsentStore (graph_store/notification_consent_store.py). The wording version is
the version of the consent text the person saw; a withdrawn consent keeps it.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class NotificationConsent:
    practitioner_id: str
    device_id: str
    wording_version: str
    status: str
    """'active' when recorded, 'inactive' when withdrawn."""
    at: datetime


class NotificationConsentStore(Protocol):
    async def record(
        self, practitioner_id: str, device_id: str, wording_version: str, at: datetime
    ) -> None:
        """Make the consent of this device active with this wording version, replacing an earlier
        consent of the same device."""
        ...

    async def withdraw(self, practitioner_id: str, device_id: str, at: datetime) -> None:
        """Mark the consent of this device inactive. The record stays for audit."""
        ...

    async def get(self, device_id: str) -> NotificationConsent | None:
        """The current consent of this device, or None when none was ever recorded."""
        ...
