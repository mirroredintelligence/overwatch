"""Capacity report: an immutable measurement sent by a service (D02).

A report is never edited. A correction is a new report. A "we are closed to referrals" report is
value=0 for a measure that counts what the service can take. Occupied patients is a count of
what is already there, so zero occupied patients does not mean closed.

Validation runs once, in __post_init__, and every failure raises ValidationFailed naming the field.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

from diucs.domain.codes import Measure, ReportSource, ReportType
from diucs.domain.errors import ValidationFailed


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
    written_at: datetime | None = field(default=None, compare=False)
    """When the store wrote the report (FHIR meta.lastUpdated, whole seconds), or None for a report
    that has not been stored. It is the record order, which an explicit effective time can differ
    from (DEC-140). Set by the repository on a read; it is not part of the report's identity, so it
    takes no part in equality, and the repository never writes it from here (U05, DEC-148)."""

    def __post_init__(self) -> None:
        # bool is an int subclass, and float('nan') is not an int: reject both by type.
        if isinstance(self.value, bool) or not isinstance(self.value, int):
            raise ValidationFailed("value", "must be a whole number")
        if self.value < 0:
            raise ValidationFailed("value", "must be zero or more")
        if self.effective_at.tzinfo is None or self.effective_at.utcoffset() is None:
            raise ValidationFailed("effective_at", "must be timezone-aware")
        if self.report_type is ReportType.CONFIRMED and self.derived_from is None:
            raise ValidationFailed(
                "derived_from", "a confirmation must name the report it confirms"
            )

    @property
    def is_closed(self) -> bool:
        return self.value == 0 and self.measure is not Measure.OCCUPIED_PATIENTS


def latest_report(reports: Iterable[CapacityReport]) -> CapacityReport | None:
    """The report with the greatest effective_at. On an exact tie, the later one in input wins."""
    latest: CapacityReport | None = None
    for candidate in reports:
        if latest is None or candidate.effective_at >= latest.effective_at:
            latest = candidate
    return latest
