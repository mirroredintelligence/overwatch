"""Report flag rules (D12): which capacity reports a shift lead should check by phone.

Rules: docs/spec/domain-rules.md section 2.3.
Names: docs/spec/contracts.md (rules/report_flags.py row).
Pure: no I/O, and no clock. Every datetime is converted to UTC before it is compared or subtracted.
This matters for London input: two datetimes with the same tzinfo object (ZoneInfo caches them)
subtract and compare wall-clock fields, so 00:58 GMT to 02:02 BST would read as 1h04 instead of
4 minutes. Both windows include their edges (see DEC-025).

A flag says "check by phone"; it never changes a report. The profile is accepted for the shared
signature; the rules depend only on the reports.

The windows and the count are tenant policy (TEN-064): `flags_for_report` takes a `TenantPolicy` as
its last argument, defaulting to `DEFAULT_POLICY`, and reads `many_changes_window`,
`many_changes_count` and `phoned_window`. The module constants are aliases of the default policy.
The function reads only the reports it is given, so a phoned position is never compared across
tenants (DEC-136 item 5): the caller loads the reports inside one tenant.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Final

from diucs.domain.codes import ReportFlagReason, ReportSource
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.service import ServiceProfile
from diucs.domain.model.tenant_policy import DEFAULT_POLICY, TenantPolicy, require_policy

# Aliases of the default policy (TEN-064): the numbers are defined once, in tenant_policy.py.
MANY_CHANGES_WINDOW: Final = DEFAULT_POLICY.many_changes_window
MANY_CHANGES_COUNT: Final = DEFAULT_POLICY.many_changes_count
PHONED_WINDOW: Final = DEFAULT_POLICY.phoned_window


def flags_for_report(
    new: CapacityReport,
    recent: Sequence[CapacityReport],
    profile: ServiceProfile,
    policy: TenantPolicy = DEFAULT_POLICY,
) -> list[ReportFlagReason]:
    """The flags raised by `new`, in rule order, each at most once.

    `recent` may or may not contain `new`; it is matched by id and counted once. Reports for other
    services, and reports later than `new`, are ignored.
    """
    policy = require_policy(policy)
    new_at = _instant(new)
    earlier = [
        r
        for r in recent
        if r.id != new.id and r.service_id == new.service_id and _instant(r) <= new_at
    ]
    flags: list[ReportFlagReason] = []
    if _many_changes(new, earlier, policy):
        flags.append(ReportFlagReason.MANY_CHANGES)
    if _differs_from_phoned(new, earlier, policy):
        flags.append(ReportFlagReason.DIFFERS_FROM_PHONED)
    return flags


def _instant(report: CapacityReport) -> datetime:
    """The report's time as UTC. Never subtract or compare the London-zoned value directly."""
    return report.effective_at.astimezone(UTC)


def _many_changes(
    new: CapacityReport, earlier: Sequence[CapacityReport], policy: TenantPolicy
) -> bool:
    start = _instant(new) - policy.many_changes_window
    in_window = sum(1 for r in earlier if _instant(r) >= start)
    return in_window + 1 >= policy.many_changes_count


def _differs_from_phoned(
    new: CapacityReport, earlier: Sequence[CapacityReport], policy: TenantPolicy
) -> bool:
    if new.source is ReportSource.ADVISOR_PHONED:
        return False
    start = _instant(new) - policy.phoned_window
    return any(
        r.source is ReportSource.ADVISOR_PHONED and _instant(r) >= start and r.value != new.value
        for r in earlier
    )
