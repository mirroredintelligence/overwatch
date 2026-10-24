"""Capacity report: an immutable measurement sent by a service (D02). Stub for the red commit (DEC-010)."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from diucs.domain.codes import Measure, ReportSource, ReportType


@dataclass(frozen=True, slots=True)
class CapacityReport:
    id: str
    service_id: str
    value: int
    measure: Measure
    effective_at: datetime
    source: ReportSource
    report_type: ReportType
    performer_role_id: str | None = None
    derived_from: str | None = None

    def __post_init__(self) -> None:
        raise NotImplementedError

    @property
    def is_closed(self) -> bool:
        raise NotImplementedError


def latest_report(reports: Iterable[CapacityReport]) -> CapacityReport | None:
    raise NotImplementedError
