"""Clinical advice requests (U40). Stub for the red commit (DEC-010)."""

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Final

from diucs.domain.model.clinical import ClinicalRequestRecord
from diucs.domain.rules.clinical_queue import Presence

PRESENCE_TTL: Final = timedelta(seconds=120)
REQUEST_WHYS: Final = frozenset({"borderline-criteria", "unsure-of-urgency", "other"})
ADVICE_CHOICES: Final = frozenset(
    {"go-ahead", "use-another-service", "clinical-call-to-referrer", "emergency-route"}
)


def presence_key(practitioner_id: str) -> str:
    raise NotImplementedError


def parse_presence(text: str | None) -> Presence | None:
    raise NotImplementedError


def validate_request(urgency: str, why: str) -> None:
    raise NotImplementedError


def validate_advice(choice: str, reason: str | None) -> None:
    raise NotImplementedError


def queue_now(
    records: Sequence[ClinicalRequestRecord], now: datetime
) -> list[ClinicalRequestRecord]:
    raise NotImplementedError


def advice_notice(urgency: str, age_band: str, need: str) -> tuple[str, str]:
    raise NotImplementedError
