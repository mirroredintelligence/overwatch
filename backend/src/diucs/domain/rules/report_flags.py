"""Report flag rules (D12): which capacity reports a shift lead should check by phone.

Rules: docs/spec/domain-rules.md section 2.3. Names: docs/spec/contracts.md, rules/report_flags.py row.
Pure: no I/O, and no clock. Windows are compared as instants (aware datetimes), so the London clock
changes do not affect them. Both windows include their edges (see DEC-023 for the phoned rule).

A flag says "check by phone"; it never changes a report. The profile is accepted for the shared
signature; the rules depend only on the reports.
"""

from collections.abc import Sequence
from datetime import timedelta

from diucs.domain.codes import ReportFlagReason, ReportSource
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.service import ServiceProfile

MANY_CHANGES_WINDOW = timedelta(minutes=5)
MANY_CHANGES_COUNT = 3
PHONED_WINDOW = timedelta(minutes=60)


def flags_for_report(
    new: CapacityReport,
    recent: Sequence[CapacityReport],
    profile: ServiceProfile,
) -> list[ReportFlagReason]:
    """The flags raised by `new`, in rule order, each at most once.

    `recent` may or may not contain `new`; it is matched by id and counted once. Reports for other
    services, and reports later than `new`, are ignored.
    """
    earlier = [
        r
        for r in recent
        if r.id != new.id and r.service_id == new.service_id and r.effective_at <= new.effective_at
    ]
    flags: list[ReportFlagReason] = []
    if _many_changes(new, earlier):
        flags.append(ReportFlagReason.MANY_CHANGES)
    if _differs_from_phoned(new, earlier):
        flags.append(ReportFlagReason.DIFFERS_FROM_PHONED)
    return flags


def _many_changes(new: CapacityReport, earlier: Sequence[CapacityReport]) -> bool:
    start = new.effective_at - MANY_CHANGES_WINDOW
    in_window = sum(1 for r in earlier if r.effective_at >= start)
    return in_window + 1 >= MANY_CHANGES_COUNT


def _differs_from_phoned(new: CapacityReport, earlier: Sequence[CapacityReport]) -> bool:
    if new.source is ReportSource.ADVISOR_PHONED:
        return False
    start = new.effective_at - PHONED_WINDOW
    return any(
        r.source is ReportSource.ADVISOR_PHONED and r.effective_at >= start and r.value != new.value
        for r in earlier
    )
