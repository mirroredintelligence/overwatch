"""Advisor cases: the referrer, need, urgency, scores and outcome of one call (D18).

Stub for the red commit (DEC-010): names and signatures only, no behaviour yet.
"""

from dataclasses import dataclass
from datetime import datetime

from diucs.domain.codes import (
    AgeBand,
    BestFitNotUsedReason,
    NeedCategory,
    Outcome,
    ReferrerType,
    Urgency,
)
from diucs.domain.model.scores import Score


@dataclass(frozen=True, slots=True)
class Case:
    id: str
    reference: str
    referrer_type: ReferrerType
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
        raise NotImplementedError

    def close(
        self,
        outcome: Outcome,
        at: datetime,
        destination_service_id: str | None = None,
        best_fit_not_used: BestFitNotUsedReason | None = None,
    ) -> Case:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class CaseAuditSummary:
    reference: str
    referrer_type: ReferrerType
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
    raise NotImplementedError


def audit_summary(
    case: Case,
    outcome: Outcome,
    at: datetime,
    destination_service_id: str | None = None,
    best_fit_not_used: BestFitNotUsedReason | None = None,
) -> CaseAuditSummary:
    raise NotImplementedError
