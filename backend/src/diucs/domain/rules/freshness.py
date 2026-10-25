"""Freshness of a service's figure: overdue, data age and the stale warning (D05).

Rules: docs/spec/domain-rules.md 1.5 and the D05 prompt. Decision DEC-027 records one deviation.
Pure: no I/O and no clock. `now` is an argument. Every instant is converted to UTC before it is
compared or subtracted (lesson L4).

Stub only (DEC-010): the red commit. The behaviour is written in the green commit.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from diucs.domain.model.service import ServiceProfile

STALE_WARNING_AFTER: Final = timedelta(hours=2)


@dataclass(frozen=True, slots=True)
class Freshness:
    overdue: bool
    age: timedelta | None
    stale_warning: bool
    was_due: datetime | None


def assess_freshness(
    profile: ServiceProfile,
    last_report_at: datetime | None,
    now: datetime,
) -> Freshness:
    raise NotImplementedError


def data_age_text(age: timedelta) -> str:
    raise NotImplementedError
