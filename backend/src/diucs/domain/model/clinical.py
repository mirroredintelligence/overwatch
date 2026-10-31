"""Clinical advice records (P18): a request for advice, and the advice given on it (U40).

The queue rules (take, return_if_idle, give_advice, queue_order) are in diucs.domain.rules.
clinical_queue (D23). Free-text notes never enter this record: only a handle to the protected text
store (P20) is kept, and the handle is a string the caller got from that store.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from diucs.domain.errors import ValidationFailed
from diucs.domain.rules.clinical_queue import ClinicalRequest


def _text(field: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValidationFailed(field, "is required")


def _optional_text(field: str, value: object) -> None:
    if value is not None:
        _text(field, value)


def _aware(field: str, value: object) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValidationFailed(field, "must carry a UTC offset")


@dataclass(frozen=True, slots=True)
class ClinicalAdvice:
    choice: str
    reason: str | None
    note_handle: str | None
    clinician_id: str
    at: datetime

    def __post_init__(self) -> None:
        _text("choice", self.choice)
        _optional_text("reason", self.reason)
        _optional_text("note_handle", self.note_handle)
        _text("clinician_id", self.clinician_id)
        _aware("at", self.at)


@dataclass(frozen=True, slots=True)
class ClinicalRequestRecord:
    request: ClinicalRequest
    requester_id: str
    why: str
    snapshot_ref: str | None
    advice: ClinicalAdvice | None = None
    service_id: str | None = None
    """The service the advisor was considering when they asked (KI-768): the advice is about it, so
    the clinician's sentence can name it. None when the advisor asked about the case as a whole."""

    def __post_init__(self) -> None:
        _text("requester_id", self.requester_id)
        _text("why", self.why)
        _optional_text("snapshot_ref", self.snapshot_ref)
        _optional_text("service_id", self.service_id)
        if self.advice is None:
            if self.request.advised_at is not None:
                raise ValidationFailed("advice", "an advised request needs its advice")
            return
        same_instant = self.request.advised_at is not None and self.request.advised_at.astimezone(
            UTC
        ) == self.advice.at.astimezone(UTC)
        if not same_instant or self.request.taken_by != self.advice.clinician_id:
            raise ValidationFailed("advice", "must be the advice given on this request")
