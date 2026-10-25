"""Effective available and pending counts (D06).

Rules: docs/spec/domain-rules.md section 1.6. Names: docs/spec/contracts.md, rules/availability.py.

A booking confirmed at exactly the report's effective_at counts as after it, so it is subtracted.
Measures are compared by identity (`is`): StrEnum members from other enums with the same value
compare equal (lesson L3), and an identity check cannot be fooled by them.
Pure: no I/O, no clock.
"""

from collections.abc import Iterable, Sequence
from datetime import datetime

from diucs.domain.codes import BookingStatus, Measure
from diucs.domain.model.capacity import CapacityReport


def _confirmed_since(report: CapacityReport, confirmed_at: Sequence[datetime]) -> int:
    return sum(1 for when in confirmed_at if when >= report.effective_at)


def effective_available(report: CapacityReport, confirmed_at: Sequence[datetime]) -> int:
    """Free places left: the reported figure less bookings confirmed since it, never below 0."""
    if report.measure is Measure.OCCUPIED_PATIENTS:
        raise ValueError("occupied-patients counts patients in; use effective_occupied")
    return max(0, report.value - _confirmed_since(report, confirmed_at))


def effective_occupied(report: CapacityReport, confirmed_at: Sequence[datetime]) -> int:
    """Occupied patients: the reported count plus one per booking confirmed since it."""
    if report.measure is not Measure.OCCUPIED_PATIENTS:
        raise ValueError("effective_occupied applies only to occupied-patients")
    return report.value + _confirmed_since(report, confirmed_at)


def pending_count(statuses: Iterable[BookingStatus]) -> int:
    """Bookings awaiting a reply. Shown apart from available; never reduces it."""
    return sum(1 for status in statuses if status is BookingStatus.REQUESTED)
