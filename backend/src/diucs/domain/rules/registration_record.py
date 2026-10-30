"""The registration record: each step of a registration with who did it and when (U29, DEC-407).
Stub: the red commit."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Final

RECORD_STEP: Final = "record"


@dataclass(frozen=True, slots=True)
class RecordedStep:
    step: str
    at: datetime | None
    by: str | None


def registration_steps(
    submitted_at: datetime | None, submitted_by: str | None, record: Mapping[str, object]
) -> tuple[RecordedStep, ...]:
    raise NotImplementedError
