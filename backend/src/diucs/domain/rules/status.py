"""Service status from profile, latest report, confirmations and clock (D07).

Rules: docs/spec/domain-rules.md 1.2 and 1.3. DEC-010 stub: no behaviour yet.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from diucs.domain.codes import Status
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.service import ServiceProfile
from diucs.domain.rules.freshness import Freshness


@dataclass(frozen=True, slots=True)
class ServiceState:
    status: Status
    effective_available: int | None
    used: int | None
    over_by: int | None
    freshness: Freshness


def compute_status(
    profile: ServiceProfile,
    latest: CapacityReport | None,
    confirmed_at: Sequence[datetime],
    now: datetime,
) -> ServiceState:
    raise NotImplementedError("D07 compute_status")
