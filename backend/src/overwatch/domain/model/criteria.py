"""Service criteria: the needs, districts and ages a service takes, as one versioned record (D20).

A criteria version is current, pending approval, draft, superseded or retired (domain-rules 4.2).
Only a current version is used to filter cases. Validation fails closed: a malformed version
cannot be built, so it cannot reach the filter.
"""

from dataclasses import dataclass
from datetime import date, datetime

from diucs.domain.codes import CriteriaStatus, NeedCategory
from diucs.domain.errors import ValidationFailed
from diucs.domain.rules.postcode import normalise_district

REVIEW_CHOICES_MONTHS: frozenset[int] = frozenset({3, 6, 12})
"""The review periods an owner may choose (domain-rules 4.2). Kept here, not imported from the
criteria workflow rules, which import this module."""


def _check_int(field: str, value: object, minimum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValidationFailed(field, f"must be a whole number of at least {minimum}")


def _check_needs(field: str, needs: object) -> None:
    # Exact enum members only: a StrEnum from another enum, or a plain string, with the same
    # value would compare equal and must not pass as a need (lesson L3).
    if not isinstance(needs, frozenset) or any(type(need) is not NeedCategory for need in needs):
        raise ValidationFailed(field, "must be a set of need categories")


def _check_districts(districts: object) -> None:
    if not isinstance(districts, frozenset):
        raise ValidationFailed("districts", "must be a set of district codes")
    for district in districts:
        if not isinstance(district, str) or normalise_district(district) != district:
            raise ValidationFailed("districts", "must be upper-case district codes")


@dataclass(frozen=True, slots=True)
class ServiceCriteria:
    id: str
    service_id: str
    version: int
    status: CriteriaStatus
    age_min: int
    age_max: int | None
    districts: frozenset[str]
    accepts: frozenset[NeedCategory]
    excludes: frozenset[NeedCategory]
    review_by: date
    owner_role_id: str
    change_reason: str = ""
    supersedes_id: str | None = None
    review_months: int | None = None
    """The review period the owner chose (3, 6 or 12 months, U30). A pending version carries it so
    that approval can set review-by from the approval date."""
    changed_on: date | None = None
    """The London day this version was proposed, and again the day it was approved (W7B B), so the
    history can say when each change was made. None for a version stored before it was kept."""

    def __post_init__(self) -> None:
        _check_int("version", self.version, minimum=1)
        if not isinstance(self.status, CriteriaStatus):
            raise ValidationFailed("status", "must be a criteria status")
        _check_int("age_min", self.age_min, minimum=0)
        if self.age_max is not None:
            _check_int("age_max", self.age_max, minimum=self.age_min)
        _check_districts(self.districts)
        _check_needs("accepts", self.accepts)
        _check_needs("excludes", self.excludes)
        if self.accepts & self.excludes:
            raise ValidationFailed("excludes", "a need cannot be both accepted and excluded")
        if self.changed_on is not None and (
            not isinstance(self.changed_on, date) or isinstance(self.changed_on, datetime)
        ):
            raise ValidationFailed("changed_on", "must be a calendar date")
        if self.review_months is not None and (
            type(self.review_months) is not int or self.review_months not in REVIEW_CHOICES_MONTHS
        ):
            raise ValidationFailed("review_months", "must be 3, 6 or 12")
