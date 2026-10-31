"""How long a projected status stays true (TEN-056, DEC-132 item 4, DEC-134 item 6, audit F 4.7).

The network stores the inputs of a status and reads it at the time of the read (DEC-546), so a
service that stops reporting turns Not updated with no event. `valid_until` is the producer's half
of that promise, written on every capacity projection: the next instant at which the status the
member's own board would compute from the same inputs could change with no new report. It is the
boundary the scheduled heartbeat re-projects at (`projection_boundaries.py`), and what a later
reader may use to tell a projection that has outlived its inputs.

The boundaries, each strictly after `now`:

- the hours change (the service opens or closes, `next_hours_change`);
- a reply-by passes that would make the service overdue: the current due time's and the next one's
  (due plus the tenant's reply window), unless a report at or after that due time exists or the
  service is already overdue (it stays so until a report, which is an event);
- the figure grows old enough to carry the stale warning (report time plus the tenant's limit).

A suspended service reads Not updated whatever the time is (rule 1 of `compute_status`), so it has
no time boundary: its next change is an event. Pure: no clock, no I/O; the tenant's policy and zone
are arguments (TEN-021, TEN-065). The oracle in the tests is `compute_status` itself.
"""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from diucs.domain.model.service import ServiceProfile
from diucs.domain.model.tenant_policy import DEFAULT_POLICY, TenantPolicy, require_policy
from diucs.domain.rules.freshness import assess_freshness
from diucs.domain.rules.london_time import LONDON, require_zone
from diucs.domain.rules.opening_hours import next_hours_change
from diucs.domain.rules.schedule import current_due, next_due


def _utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def next_status_change(
    profile: ServiceProfile,
    last_report_at: datetime | None,
    now: datetime,
    policy: TenantPolicy = DEFAULT_POLICY,
    zone: ZoneInfo = LONDON,
) -> datetime | None:
    """The next instant after `now` at which the status could change with no new report, or None
    when nothing time-driven is ahead (a suspended service, or no hours at all)."""
    policy = require_policy(policy)
    zone = require_zone(zone)
    at = _utc(now, "now")
    last = None if last_report_at is None else _utc(last_report_at, "last_report_at")
    if last is not None and last > at:
        raise ValueError("last_report_at must not be after now")
    if profile.suspended:
        return None
    candidates: list[datetime] = []
    hours = next_hours_change(profile.available_times, at, zone)
    if hours is not None:
        candidates.append(hours)
    # Once overdue, a service stays overdue until a report arrives (an event): a later reply-by
    # changes nothing.
    if not assess_freshness(profile, last, at, policy, zone).overdue:
        for due in (current_due(profile, at, policy, zone), next_due(profile, at, policy, zone)):
            if due is None or (last is not None and due <= last):
                continue
            reply_by = due + policy.reply_window
            if reply_by > at:
                candidates.append(reply_by)
    if last is not None:
        warned = last + policy.stale_warning_after
        if warned > at:
            candidates.append(warned)
    return min(candidates, default=None)
