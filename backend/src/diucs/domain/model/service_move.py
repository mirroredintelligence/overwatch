"""A service move (P20, U38): a service's accepting status moves to another phone for a while.

Only the hash of the phone number is kept, never the number. At most one move per service is open
(not completed, not cancelled); the store enforces that under the service's lock.
"""

from dataclasses import dataclass
from datetime import datetime

from diucs.domain.errors import ValidationFailed


def _text(field: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValidationFailed(field, "is required")


def _optional_aware(field: str, value: datetime | None) -> None:
    if value is None:
        return
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValidationFailed(field, "must carry a UTC offset")


@dataclass(frozen=True, slots=True)
class ServiceMove:
    id: str
    service_id: str
    from_practitioner_id: str
    to_phone_hash: str
    until: datetime | None
    code_verified_at: datetime | None = None
    callback_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None

    def __post_init__(self) -> None:
        _text("id", self.id)
        _text("service_id", self.service_id)
        _text("from_practitioner_id", self.from_practitioner_id)
        _text("to_phone_hash", self.to_phone_hash)
        for name in ("until", "code_verified_at", "callback_at", "completed_at", "cancelled_at"):
            _optional_aware(name, getattr(self, name))
        if self.completed_at is not None and self.cancelled_at is not None:
            raise ValidationFailed("cancelled_at", "a move is completed or cancelled, not both")

    @property
    def is_open(self) -> bool:
        return self.completed_at is None and self.cancelled_at is None
