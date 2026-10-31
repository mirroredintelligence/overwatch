"""Is a prompt's due time inside the service's hours (DEC-1100 Q3, KI-22).

`is_in_hours` is end-exclusive, which the status rule needs: a service is not taking referrals at
its closing time. A service that reports every two hours has a due time at its closing time
(domain-rules 1.4: every two hours from the opening up to and including the closing time), and that
last prompt is the closing figure a night coordinator relies on. For due times only, the closing
time counts as inside the hours. Nothing else changes: a time a tick after the closing time is
outside, and `is_in_hours` is untouched.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Final
from zoneinfo import ZoneInfo

from diucs.domain.model.service import AvailableTime
from diucs.domain.rules.london_time import LONDON
from diucs.domain.rules.opening_hours import is_in_hours

ONE_TICK: Final = timedelta(microseconds=1)


def is_due_time_in_hours(
    times: Sequence[AvailableTime], due: datetime, zone: ZoneInfo = LONDON
) -> bool:
    """True when a prompt due at `due` is inside a window, the window's closing time included. A
    naive time is refused (ValueError). The windows are read in `zone`."""
    if due.utcoffset() is None:
        raise ValueError("a due time must be timezone-aware")
    return is_in_hours(times, due, zone) or is_in_hours(times, due - ONE_TICK, zone)
