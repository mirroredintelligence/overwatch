"""Clinical advice queue and presence rules (D23). DEC-010 stub: no behaviour yet."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final, Iterable

TAKE_TIMEOUT: Final = timedelta(minutes=10)
NOTE_MAX: Final = 280


class Presence(StrEnum):
    AVAILABLE = "available"
    BUSY = "busy"
    AWAY = "away"


@dataclass(frozen=True, slots=True)
class ClinicalRequest:
    id: str
    case_id: str
    urgency: str
    requested_at: datetime
    taken_by: str | None = None
    taken_at: datetime | None = None
    advised_at: datetime | None = None


def take(request: ClinicalRequest, clinician_id: str, now: datetime) -> ClinicalRequest:
    raise NotImplementedError


def return_if_idle(request: ClinicalRequest, now: datetime) -> ClinicalRequest:
    raise NotImplementedError


def give_advice(request: ClinicalRequest, clinician_id: str, now: datetime) -> ClinicalRequest:
    raise NotImplementedError


def release_for_away(
    requests: Iterable[ClinicalRequest], clinician_id: str
) -> list[ClinicalRequest]:
    raise NotImplementedError


def available_count(presences: Iterable[Presence]) -> int:
    raise NotImplementedError


def advice_shown_as_available(available: int | None, queue_known: bool) -> bool:
    raise NotImplementedError


def queue_order(requests: Iterable[ClinicalRequest]) -> list[ClinicalRequest]:
    raise NotImplementedError


def validate_note(note: str) -> None:
    raise NotImplementedError
