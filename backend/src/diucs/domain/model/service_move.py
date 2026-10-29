"""A service move (P20, U38): a service's accepting status moves to another phone for a while.

Only the hash of the phone number is kept, never the number. At most one move per service is open
(not completed, not cancelled). Red stub: validation is added with the implementation (DEC-010).
"""

from dataclasses import dataclass
from datetime import datetime


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

    @property
    def is_open(self) -> bool:
        return self.completed_at is None and self.cancelled_at is None
