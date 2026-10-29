"""Criteria change, approval, confirmation and history (U30, docs/spec/domain-rules.md section 4.2).

Stub for the red commit (DEC-010): the public names exist, every body raises NotImplementedError.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from diucs.application.actor import Actor
from diucs.domain.codes import CriteriaStatus, NeedCategory
from diucs.domain.model.criteria import ServiceCriteria
from diucs.domain.model.people import PractitionerRole


@dataclass(frozen=True, slots=True)
class CriteriaValues:
    age_min: int
    age_max: int | None
    accepts: frozenset[NeedCategory]
    excludes: frozenset[NeedCategory]
    districts: frozenset[str]


def pending_version(
    *,
    current: ServiceCriteria,
    new_id: str,
    owner_role_id: str,
    values: CriteriaValues,
    change_reason: str,
    review_months: int,
    today: date,
) -> ServiceCriteria:
    raise NotImplementedError


def check_may_change(
    roles: Sequence[PractitionerRole], *, service_id: str, owner_role_id: str, now: datetime
) -> None:
    raise NotImplementedError


def check_may_approve(
    roles: Sequence[PractitionerRole], *, service_id: str, author_role_id: str | None, now: datetime
) -> None:
    raise NotImplementedError


def approved_versions(
    current: ServiceCriteria | None, pending: ServiceCriteria, today: date
) -> tuple[ServiceCriteria | None, ServiceCriteria]:
    raise NotImplementedError


def confirmed_review_by(today: date, months: int) -> date:
    raise NotImplementedError


@dataclass(frozen=True, slots=True)
class ChangeCriteriaCommand:
    idempotency_key: str
    actor: Actor
    service_id: str
    values: CriteriaValues
    change_reason: str
    review_months: int


@dataclass(frozen=True, slots=True)
class ChangeCriteriaResult:
    criteria_id: str
    version: int
    status: CriteriaStatus
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class ApproveCriteriaCommand:
    idempotency_key: str
    actor: Actor
    criteria_id: str
    decision: Literal["approve", "send-back"]
    note: str = ""


@dataclass(frozen=True, slots=True)
class ApproveCriteriaResult:
    criteria_id: str
    status: CriteriaStatus
    review_by: date | None
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class ConfirmCriteriaCommand:
    idempotency_key: str
    actor: Actor
    service_id: str
    review_months: int


@dataclass(frozen=True, slots=True)
class ConfirmCriteriaResult:
    criteria_id: str
    review_by: date
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class CriteriaHistoryQuery:
    actor: Actor
    service_id: str


@dataclass(frozen=True, slots=True)
class CriteriaVersionView:
    criteria_id: str
    version: int
    status: CriteriaStatus
    review_by: date
    author_role_id: str
