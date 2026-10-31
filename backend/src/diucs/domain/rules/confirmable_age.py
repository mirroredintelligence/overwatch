"""How old a figure may be for a Y to confirm it, per service (DEC-1100 Q4, KI-27).

A Y confirms the figure on record, so it must not make an old figure current (H-31). The line was
one for every service, the tenant's stale limit (two hours), and a service that reports less often
than every two hours could never confirm: its figure was older than that whenever the prompt went
out. The window is now the larger of the tenant's stale limit and the service's own reporting
interval, capped at 26 hours, so a daily ward can confirm yesterday's figure and nothing older than
a day and two hours ever confirms. A service that reports every two hours keeps the two hours.

[ASSUMED]: the intervals below and the cap are the owner's provisional answer (DEC-1100 Q4); the
relaxation of H-31 and H-32 is signed off with Q2. A twice-a-day service is given the longer of the
two gaps of the default times (08:00 and 14:00: 6 and 18 hours).
"""

from datetime import timedelta
from typing import Final

from diucs.domain.codes import Cadence
from diucs.domain.model.service import ServiceProfile
from diucs.domain.model.tenant_policy import DEFAULT_POLICY, TenantPolicy, require_policy

REPORTING_INTERVAL: Final[dict[Cadence, timedelta]] = {
    Cadence.EVERY_2_HRS: timedelta(hours=2),
    Cadence.TWICE_A_DAY: timedelta(hours=18),
    Cadence.ONCE_A_DAY: timedelta(hours=24),
}
MAX_CONFIRMABLE_AGE: Final = timedelta(hours=26)


def confirmable_age(profile: ServiceProfile, policy: TenantPolicy = DEFAULT_POLICY) -> timedelta:
    """The oldest a figure of this service may be, at the moment a prompt names it, for a Y to
    confirm it: the larger of the tenant's stale limit and the service's reporting interval (never
    more than 26 hours). A tenant's own limit longer than 26 hours is not shortened."""
    policy = require_policy(policy)
    interval = min(REPORTING_INTERVAL[profile.cadence], MAX_CONFIRMABLE_AGE)
    return max(policy.stale_warning_after, interval)
