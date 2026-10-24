"""Service reporting profile: validated value objects (D01). Stub for the red commit (DEC-010).

Signatures match docs/spec/contracts.md. Behaviour is not implemented yet.
"""

from dataclasses import dataclass
from datetime import time

from diucs.domain.codes import Cadence, Channel, Measure, ServiceCategory


@dataclass(frozen=True, slots=True)
class AvailableTime:
    days: frozenset[int]
    all_day: bool
    start: time | None
    end: time | None

    def __post_init__(self) -> None:
        raise NotImplementedError

    @classmethod
    def weekdays(cls, start: time, end: time) -> "AvailableTime":
        raise NotImplementedError

    @classmethod
    def every_day(cls, start: time, end: time) -> "AvailableTime":
        raise NotImplementedError

    @classmethod
    def every_day_all_day(cls) -> "AvailableTime":
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class ServiceProfile:
    id: str
    name: str
    category: ServiceCategory
    measure: Measure
    unit_label: str
    established_capacity: int
    can_exceed_established: bool
    usual_range: tuple[int, int]
    cadence: Cadence
    available_times: tuple[AvailableTime, ...]
    channel: Channel
    limited_level_percent: int = 80
    active: bool = True
    suspended: bool = False
    comment: str = ""

    def __post_init__(self) -> None:
        raise NotImplementedError
