"""Advisor cases: the referrer, need, urgency, scores and outcome of one call (D18).

A case holds no name, no NHS number and no free text. Closing a case clears the postcode and the
needs; the audit summary keeps what audit needs and is taken before close. Times are UTC.
"""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Final

from diucs.domain.codes import (
    AcuityMethod,
    AgeBand,
    BestFitNotUsedReason,
    NeedCategory,
    Outcome,
    ReferrerType,
    Urgency,
)
from diucs.domain.errors import InvalidTransition, ValidationFailed
from diucs.domain.model.scores import Score, method_of

PRIORITY_URGENT: Final = "urgent"
PRIORITY_ROUTINE: Final = "routine"


def _check_utc(field: str, value: object) -> None:
    if not isinstance(value, datetime) or value.utcoffset() != timedelta(0):
        raise ValidationFailed(field, "must be a timezone-aware UTC datetime")


def _check_one_score_per_method(scores: tuple[Score, ...]) -> None:
    seen: set[AcuityMethod] = set()
    for score in scores:
        method = method_of(score)
        if method in seen:
            raise ValidationFailed("scores", "at most one score per method")
        seen.add(method)


def _check_open(case: Case) -> None:
    if case.closed_at is not None:
        raise InvalidTransition("the case is already closed")


def _check_close(outcome: Outcome, at: datetime, destination_service_id: str | None) -> None:
    _check_utc("closed_at", at)
    if outcome is Outcome.ACCEPTED_AND_BOOKED and (
        destination_service_id is None or not destination_service_id.strip()
    ):
        raise ValidationFailed(
            "destination_service_id", "accepted and booked needs a destination service"
        )


@dataclass(frozen=True, slots=True)
class Case:
    id: str
    reference: str
    referrer_type: ReferrerType | None
    age_band: AgeBand | None
    postcode: str | None
    needs: tuple[NeedCategory, ...]
    urgency: Urgency | None
    scores: tuple[Score, ...]
    opened_at: datetime
    closed_at: datetime | None = None
    outcome: Outcome | None = None
    best_fit_not_used: BestFitNotUsedReason | None = None
    destination_service_id: str | None = None

    def __post_init__(self) -> None:
        _check_utc("opened_at", self.opened_at)
        _check_one_score_per_method(self.scores)

    def close(
        self,
        outcome: Outcome,
        at: datetime,
        destination_service_id: str | None = None,
        best_fit_not_used: BestFitNotUsedReason | None = None,
    ) -> Case:
        _check_open(self)
        _check_close(outcome, at, destination_service_id)
        return replace(
            self,
            postcode=None,
            needs=(),
            closed_at=at,
            outcome=outcome,
            best_fit_not_used=best_fit_not_used,
            destination_service_id=destination_service_id,
        )


@dataclass(frozen=True, slots=True)
class CaseAuditSummary:
    reference: str
    referrer_type: ReferrerType | None
    age_band: AgeBand | None
    needs: tuple[NeedCategory, ...]
    urgency: Urgency | None
    scores: tuple[Score, ...]
    outcome: Outcome
    best_fit_not_used: BestFitNotUsedReason | None
    destination_service_id: str | None
    opened_at: datetime
    closed_at: datetime


def priority_for(urgency: Urgency) -> str:
    # Explicit on every member, so an unknown urgency fails rather than falling to routine.
    match urgency:
        case Urgency.WITHIN_2_HRS:
            return PRIORITY_URGENT
        case Urgency.TODAY | Urgency.PLANNED:
            return PRIORITY_ROUTINE
    raise ValidationFailed("urgency", "not a known urgency")


def audit_summary(
    case: Case,
    outcome: Outcome,
    at: datetime,
    destination_service_id: str | None = None,
    best_fit_not_used: BestFitNotUsedReason | None = None,
) -> CaseAuditSummary:
    _check_open(case)
    _check_close(outcome, at, destination_service_id)
    return CaseAuditSummary(
        reference=case.reference,
        referrer_type=case.referrer_type,
        age_band=case.age_band,
        needs=case.needs,
        urgency=case.urgency,
        scores=case.scores,
        outcome=outcome,
        best_fit_not_used=best_fit_not_used,
        destination_service_id=destination_service_id,
        opened_at=case.opened_at,
        closed_at=at,
    )
