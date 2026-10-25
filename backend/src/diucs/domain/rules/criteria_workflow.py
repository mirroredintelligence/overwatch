"""Criteria version workflow and review dates (D21, docs/spec/domain-rules.md section 4.2).

Pure: no I/O. Dates are calendar dates, the London day. Callers derive it from an instant with
london_time.to_london(instant).date(); this module never receives a datetime as a date (DEC-036).
Enum inputs are checked as members of CriteriaStatus, so another enum with the same value is
refused (lesson L3, L38).
"""

import calendar
from collections.abc import Mapping
from dataclasses import replace
from datetime import date, datetime, timedelta
from types import MappingProxyType

from diucs.domain.codes import CriteriaStatus
from diucs.domain.errors import InvalidTransition, ValidationFailed
from diucs.domain.model.criteria import ServiceCriteria

REVIEW_REMINDER_BEFORE = timedelta(days=14)
"""[ASSUMED] the reminder is due from this long before review-by, up to and including it."""

REVIEW_PERIOD_MONTHS = frozenset({3, 6, 12})

_C = CriteriaStatus

# domain-rules 4.2: the only legal moves. Retiring is allowed from every status except retired.
_ALLOWED: Mapping[CriteriaStatus, frozenset[CriteriaStatus]] = MappingProxyType(
    {
        _C.DRAFT: frozenset({_C.PENDING_APPROVAL, _C.RETIRED}),
        _C.PENDING_APPROVAL: frozenset({_C.CURRENT, _C.DRAFT, _C.RETIRED}),
        _C.CURRENT: frozenset({_C.SUPERSEDED, _C.RETIRED}),
        _C.SUPERSEDED: frozenset({_C.RETIRED}),
        _C.RETIRED: frozenset(),
    }
)


def _status(value: object, field: str) -> CriteriaStatus:
    if not isinstance(value, CriteriaStatus):
        raise ValidationFailed(field, "not a criteria status")
    return value


def _calendar_date(value: object, field: str) -> date:
    # datetime is a subclass of date: refuse it explicitly so an instant cannot pass as a day.
    if not isinstance(value, date) or isinstance(value, datetime):
        raise ValidationFailed(field, "must be a calendar date, not a datetime")
    return value


def transition_criteria(current: CriteriaStatus, target: CriteriaStatus) -> CriteriaStatus:
    checked_current = _status(current, "current")
    checked_target = _status(target, "target")
    if checked_target not in _ALLOWED[checked_current]:
        raise InvalidTransition(
            f"criteria cannot move from {checked_current.value} to {checked_target.value}"
        )
    return checked_target


def is_review_overdue(criteria: ServiceCriteria, today: date) -> bool:
    """True after review-by has passed: today is later than review-by."""
    return _calendar_date(today, "today") > criteria.review_by


def review_reminder_due(criteria: ServiceCriteria, today: date) -> bool:
    """True from REVIEW_REMINDER_BEFORE before review-by, up to and including review-by."""
    checked_today = _calendar_date(today, "today")
    return criteria.review_by - REVIEW_REMINDER_BEFORE <= checked_today <= criteria.review_by


def next_review_by(confirmed_on: date, months: int) -> date:
    """Review-by after a confirmation: months later, clamped to the month's last day."""
    start = _calendar_date(confirmed_on, "confirmed_on")
    if type(months) is not int or months not in REVIEW_PERIOD_MONTHS:
        raise ValidationFailed("months", "must be 3, 6 or 12")
    month_index = start.month - 1 + months
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(start.day, last_day))


def approve(
    current: ServiceCriteria | None, pending: ServiceCriteria
) -> tuple[ServiceCriteria | None, ServiceCriteria]:
    """Make a pending version current and supersede the current one (never delete it).

    Returns (the old version marked superseded, or None, and the new version marked current).
    The second approver is checked by the use case (U30), not here.
    """
    # A pending version can only become current; any other status is refused here.
    new_status = transition_criteria(pending.status, CriteriaStatus.CURRENT)
    if current is None:
        return None, replace(pending, status=new_status)
    if pending.service_id != current.service_id:
        raise ValidationFailed("service_id", "pending version belongs to another service")
    if pending.version != current.version + 1 or pending.supersedes_id != current.id:
        raise ValidationFailed("version", "pending version must supersede the current version")
    old_status = transition_criteria(current.status, CriteriaStatus.SUPERSEDED)
    return replace(current, status=old_status), replace(pending, status=new_status)
