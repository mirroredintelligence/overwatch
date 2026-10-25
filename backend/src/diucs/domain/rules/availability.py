"""Effective available and pending counts (D06). Stub for the red commit only (DEC-010): no behaviour."""

from collections.abc import Iterable, Sequence
from datetime import datetime

from diucs.domain.codes import BookingStatus
from diucs.domain.model.capacity import CapacityReport


def effective_available(report: CapacityReport, confirmed_at: Sequence[datetime]) -> int:
    raise NotImplementedError


def effective_occupied(report: CapacityReport, confirmed_at: Sequence[datetime]) -> int:
    raise NotImplementedError


def pending_count(statuses: Iterable[BookingStatus]) -> int:
    raise NotImplementedError
