"""Criteria version workflow and review dates (D21, docs/spec/domain-rules.md section 4.2).

Stub for the red commit (DEC-010). Replaced by the implementation.
"""

from datetime import date, timedelta

from diucs.domain.codes import CriteriaStatus
from diucs.domain.model.criteria import ServiceCriteria

REVIEW_REMINDER_BEFORE = timedelta(days=14)


def transition_criteria(current: CriteriaStatus, target: CriteriaStatus) -> CriteriaStatus:
    raise NotImplementedError


def is_review_overdue(criteria: ServiceCriteria, today: date) -> bool:
    raise NotImplementedError


def review_reminder_due(criteria: ServiceCriteria, today: date) -> bool:
    raise NotImplementedError


def next_review_by(confirmed_on: date, months: int) -> date:
    raise NotImplementedError


def approve(
    current: ServiceCriteria | None, pending: ServiceCriteria
) -> tuple[ServiceCriteria | None, ServiceCriteria]:
    raise NotImplementedError
