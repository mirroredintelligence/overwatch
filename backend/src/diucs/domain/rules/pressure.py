"""System pressure from the statuses of all services (D08). Rule: docs/spec/domain-rules.md 1.7.

D08 stub (DEC-010): declarations only. The functions raise NotImplementedError until the green commit.
"""

from collections.abc import Iterable
from enum import StrEnum
from typing import Final

from diucs.domain.codes import Status


class Pressure(StrEnum):
    NORMAL = "normal"
    WATCH = "watch"
    HIGH = "high"


WATCH_FROM: Final = 3  # [ASSUMED] rule book 1.7
HIGH_FROM: Final = 5  # rule book 1.7, also the exec alert threshold
LIMITED_OR_WORSE: Final[frozenset[Status]] = frozenset(
    {Status.LIMITED, Status.NOT_ACCEPTING, Status.OVER_CAPACITY}
)


def limited_or_worse_count(statuses: Iterable[Status]) -> int:
    raise NotImplementedError("D08 limited_or_worse_count")


def system_pressure(statuses: Iterable[Status]) -> Pressure:
    raise NotImplementedError("D08 system_pressure")


def all_limited_or_worse(statuses: Iterable[Status]) -> bool:
    raise NotImplementedError("D08 all_limited_or_worse")
