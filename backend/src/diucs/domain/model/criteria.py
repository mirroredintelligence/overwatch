"""Service criteria: the needs, districts and ages a service takes, as one versioned record (D20).

DEC-010 red stub: fields only. Validation and behaviour come in the implementation commit.
"""

from dataclasses import dataclass
from datetime import date

from diucs.domain.codes import CriteriaStatus, NeedCategory


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
