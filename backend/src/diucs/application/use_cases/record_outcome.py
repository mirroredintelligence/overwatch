"""RecordOutcome: the advisor records how a case ended, and the case closes (U14). Red stub."""

from dataclasses import dataclass
from datetime import datetime

from diucs.domain.codes import Outcome
from diucs.domain.model.case import Case


@dataclass(frozen=True, slots=True)
class RecordOutcomeCommand:
    idempotency_key: str
    actor: object
    case_id: str
    outcome: Outcome
    destination_service_id: str | None = None
    best_fit_not_used: object = None


def check_destination(outcome: Outcome, destination_service_id: str | None) -> None:
    raise NotImplementedError


def build_summary(
    case: Case,
    *,
    destination_name: str | None,
    booking_line: str | None,
    data_age_line: str | None,
) -> list[tuple[str, str]]:
    raise NotImplementedError


__all__ = ["RecordOutcomeCommand", "Case", "datetime", "check_destination", "build_summary"]
