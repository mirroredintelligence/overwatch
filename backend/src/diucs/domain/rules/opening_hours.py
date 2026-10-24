"""Opening hours: is a service taking referrals at a given moment (D03).

Stub only (DEC-010): the behaviour is not built yet.
"""

from collections.abc import Sequence
from datetime import datetime

from diucs.domain.model.service import AvailableTime


def is_in_hours(times: Sequence[AvailableTime], now: datetime) -> bool:
    raise NotImplementedError


def next_opening(times: Sequence[AvailableTime], now: datetime) -> datetime | None:
    raise NotImplementedError
