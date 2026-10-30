"""Rules for acknowledging, snoozing and checking alerts (U34). Stub: the red commit."""

from datetime import datetime, timedelta
from typing import Final

SNOOZE_BY: Final = timedelta(hours=1)


def snoozed_due(due: datetime) -> datetime:
    raise NotImplementedError


def may_acknowledge(status: str, *, owner_id: str, actor_id: str | None) -> None:
    raise NotImplementedError


def may_snooze(status: str, *, owner_id: str, actor_id: str | None) -> None:
    raise NotImplementedError


def not_updated_check_times(changed_at: datetime) -> tuple[datetime, datetime]:
    raise NotImplementedError
