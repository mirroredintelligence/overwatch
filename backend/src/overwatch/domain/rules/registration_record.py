"""The registration record: each step of a registration with who did it and when (U29, DEC-407).

The approval steps are kept in the registration's draft as typed text fields: `<step>_at` (an ISO
instant with its zone) and `<step>_by` (the practitioner or role id). Submission is the
registration's own submitted_at. The call-back, scope and criteria steps are judged from the stored
checks and have no time of their own, so they come last with no time.

Pure: no I/O and no clock.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from diucs.domain.errors import ValidationFailed

RECORD_STEP: Final = "record"
# (step name in the record, the prefix of its fields)
_TIMED: Final = (
    ("approved", "approved"),
    ("sent-back", "sent_back"),
    ("not-approved", "not_approved"),
    ("test-prompt", "test_prompt"),
    ("test-answered", "test_answered"),
    ("set-live", "live"),
)
_UNTIMED: Final = ("call-back", "scope", "criteria")
_EARLIEST: Final = datetime.min.replace(tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class RecordedStep:
    step: str
    at: datetime | None
    by: str | None


def _instant(field: str, text: object) -> datetime:
    if not isinstance(text, str):
        raise ValidationFailed(field, "must be text")
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        raise ValidationFailed(field, "must be an ISO instant") from None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValidationFailed(field, "must be timezone-aware")
    return value


def _text_or_none(record: Mapping[str, object], key: str) -> str | None:
    value = record.get(key)
    return value if isinstance(value, str) else None


def registration_steps(
    submitted_at: datetime | None, submitted_by: str | None, record: Mapping[str, object]
) -> tuple[RecordedStep, ...]:
    """The timed steps in time order, then the untimed ones (no time). A timed step with no record
    is left out; the untimed three always appear."""
    timed: list[RecordedStep] = []
    if submitted_at is not None:
        timed.append(RecordedStep("submitted", submitted_at, submitted_by))
    for step, prefix in _TIMED:
        raw = record.get(f"{prefix}_at")
        if raw is None:
            continue
        instant = _instant(f"{prefix}_at", raw)
        timed.append(RecordedStep(step, instant, _text_or_none(record, f"{prefix}_by")))
    timed.sort(key=lambda item: item.at or _EARLIEST)
    untimed = [RecordedStep(step, None, None) for step in _UNTIMED]
    return (*timed, *untimed)
