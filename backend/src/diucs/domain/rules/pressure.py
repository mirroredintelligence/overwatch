"""System pressure from the statuses of all services (D08). Rule: docs/spec/domain-rules.md 1.7.

Pure: no I/O and no clock. Limited or worse is limited, not-accepting or over-capacity. Not-updated
is unknown, so it neither counts nor stops the count; out-of-hours is left out entirely. The board
banner shows when every in-hours service is limited or worse. Thresholds are named constants from
the rule book, not literals.

Each status must be a Status member of exactly this enum. A plain string with the same value, or a
member of another enum, is refused with TypeError rather than counted (DEC-040, lesson L44). Input
is read once, so a generator is safe.
"""

from collections.abc import Iterable
from enum import StrEnum
from typing import Final

from diucs.domain.codes import Status
from diucs.domain.model.tenant_policy import DEFAULT_POLICY, TenantPolicy


class Pressure(StrEnum):
    NORMAL = "normal"
    WATCH = "watch"
    HIGH = "high"


WATCH_FROM: Final = 3  # [ASSUMED] rule book 1.7
HIGH_FROM: Final = 5  # rule book 1.7, also the exec alert threshold
LIMITED_OR_WORSE: Final[frozenset[Status]] = frozenset(
    {Status.LIMITED, Status.NOT_ACCEPTING, Status.OVER_CAPACITY}
)


def _checked(statuses: Iterable[Status]) -> tuple[Status, ...]:
    """Read the input once and refuse anything that is not exactly a Status member."""
    checked = tuple(statuses)
    for status in checked:
        if type(status) is not Status:
            raise TypeError(f"expected Status, got {type(status).__name__}")
    return checked


def limited_or_worse_count(statuses: Iterable[Status]) -> int:
    return sum(1 for status in _checked(statuses) if status in LIMITED_OR_WORSE)


def system_pressure(statuses: Iterable[Status], policy: TenantPolicy = DEFAULT_POLICY) -> Pressure:
    count = limited_or_worse_count(statuses)
    if count >= HIGH_FROM:
        return Pressure.HIGH
    if count >= WATCH_FROM:
        return Pressure.WATCH
    return Pressure.NORMAL


def all_limited_or_worse(statuses: Iterable[Status]) -> bool:
    in_hours = [status for status in _checked(statuses) if status is not Status.OUT_OF_HOURS]
    return bool(in_hours) and all(status in LIMITED_OR_WORSE for status in in_hours)
