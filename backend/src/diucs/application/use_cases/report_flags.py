"""Report flags raised when a capacity report breaks a rule (U07).

A flag says "a lead should check this report by phone". It is its own record: the report is stored
whatever the flags are, and is never edited (domain-rules 2.3). `record_report` (U01) calls this
inside the unit of work that stores the report, so every path that writes a report (a number, a
confirmation) is judged by the same rules and the flags commit or roll back with the report.

Rules: `flags_for_report` (D12, DEC-025) for `many-changes` and `differs-from-phoned`; the
reply policy (D11) decides `out-of-range-twice` and the caller passes it as `extra`. Decisions:
DEC-161.
"""

from datetime import UTC, datetime, timedelta
from typing import Final

from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.outbox import outbox_message_for
from diucs.application.ports.outbound.unit_of_work import UnitOfWork
from diucs.domain.codes import ReportFlagReason
from diucs.domain.errors import ValidationFailed
from diucs.domain.events import ReportFlagged
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.flags import REPORT_FLAG_OPEN, ReportFlag
from diucs.domain.model.service import ServiceProfile
from diucs.domain.model.tenant_policy import DEFAULT_POLICY, TenantPolicy
from diucs.domain.rules.report_flags import MANY_CHANGES_WINDOW, PHONED_WINDOW, flags_for_report

LOOKBACK: Final = max(MANY_CHANGES_WINDOW, PHONED_WINDOW)
"""How far before a report the rules look: the longer of the two windows (DEC-161 item 2)."""


def report_lookback(policy: TenantPolicy = DEFAULT_POLICY) -> timedelta:
    """How far before a report the rules look under this policy: the longer of its two windows."""
    return max(policy.many_changes_window, policy.phoned_window)


async def raise_report_flags(
    uow: UnitOfWork,
    ids: IdGenerator,
    *,
    profile: ServiceProfile,
    report: CapacityReport,
    extra: ReportFlagReason | None,
    now: datetime,
    policy: TenantPolicy = DEFAULT_POLICY,
) -> list[str]:
    """Raise the flags `report` earns, and return their ids (empty when there are none).

    `report` is already added in this unit of work and the caller holds the service lock, so the
    open-flag check below cannot race another report for the same service. The reasons are the
    rules' reasons in rule order, then `extra`, each once. A reason that already has an open flag
    for this service raises nothing (one open flag per service and reason). Each new flag is
    stored open on the report and announced by a `ReportFlagged` outbox message. The windows are the
    tenant's `policy` (TEN-024); the default is today's.
    """
    if report.service_id != profile.id:
        raise ValidationFailed("report", "is not for this service")
    since = report.effective_at.astimezone(UTC) - report_lookback(policy)
    recent = await uow.capacity.reports_since(profile.id, since)
    reasons = flags_for_report(report, recent, profile, policy)
    if extra is not None and extra not in reasons:
        reasons.append(extra)
    if not reasons:
        return []
    already_open = {flag.reason for flag in await uow.flags.open_report_flags(profile.id)}
    raised: list[str] = []
    for reason in reasons:
        if reason in already_open:
            continue
        flag = ReportFlag(
            id=ids.new_id(),
            report_id=report.id,
            service_id=profile.id,
            reason=reason,
            status=REPORT_FLAG_OPEN,
            created_at=now,
        )
        await uow.flags.add_report_flag(flag)
        await uow.outbox.add(
            outbox_message_for(
                ReportFlagged(
                    flag_id=flag.id,
                    service_id=profile.id,
                    report_id=report.id,
                    reason=reason,
                    at=now,
                ),
                id=ids.new_id(),
                now=now,
            )
        )
        raised.append(flag.id)
    return raised
