"""FilterOptions: the services that may take a case, and why the others may not (U12). Red stub."""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Final

from diucs.application.actor import Actor
from diucs.domain.codes import NeedCategory, Status
from diucs.domain.model.criteria import ServiceCriteria
from diucs.domain.rules.freshness import STALE_WARNING_AFTER

NOT_ACCEPTING_REASON: Final = "not accepting"
OUT_OF_HOURS_REASON: Final = "out of hours"
OUTSIDE_CRITERIA_REASON: Final = "outside criteria"
SUSPENDED_REASON: Final = "suspended. Phone to confirm."
LIMITED_WARNING: Final = "Limited: phone to confirm"
OVER_CAPACITY_WARNING: Final = "Over capacity now. Phone to confirm before offering."
OLD_DATA_WARNING: Final = "Data is over 2 hrs old. Consider phoning."
CRITERIA_NOT_REVIEWED_WARNING: Final = "Criteria not reviewed"
COVERS_POSTCODE: Final = "Covers this postcode"

__all__ = ["STALE_WARNING_AFTER", "Actor", "date", "timedelta", "ServiceCriteria"]


@dataclass(frozen=True, slots=True)
class FilterOptionsCommand:
    idempotency_key: str
    actor: Actor
    case_id: str


def status_reason(status: Status, data_age: timedelta | None) -> str | None:
    raise NotImplementedError


def status_warnings(status: Status) -> tuple[str, ...]:
    raise NotImplementedError


def data_age_warnings(data_age: timedelta | None) -> tuple[str, ...]:
    raise NotImplementedError


def criteria_warnings(criteria: ServiceCriteria, today: date) -> tuple[str, ...]:
    raise NotImplementedError


def fits_for(criteria: ServiceCriteria, needs: tuple[NeedCategory, ...]) -> tuple[str, ...]:
    raise NotImplementedError
