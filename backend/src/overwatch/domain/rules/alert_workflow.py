"""Rules for acknowledging, snoozing and checking alerts (U34).

Rules: docs/spec/domain-rules.md section 4 (alerts) and docs/spec/architecture.md F6. Pure: no I/O
and no clock. Only the owner of an alert acts on it. An alert can be acknowledged while it is new or
escalated, anywhere in its chain (escalation takes the alert to the deputy and then the shift lead);
a snooze applies to a new alert only and moves its escalation one hour later.
"""

from datetime import UTC, datetime, timedelta
from typing import Final

from diucs.domain.errors import InvalidTransition, NotAllowed
from diucs.domain.rules.alerts import NOT_UPDATED_HOURS

SNOOZE_BY: Final = timedelta(hours=1)
_ACKNOWLEDGEABLE: Final = frozenset({"new", "escalated"})
_SNOOZABLE: Final = frozenset({"new"})


def _owner_only(owner_id: str, actor_id: str | None) -> None:
    if actor_id is None or actor_id != owner_id:
        raise NotAllowed("only the owner of this alert can act on it")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware (UTC)")
    return value.astimezone(UTC)


def snoozed_due(due: datetime) -> datetime:
    """The escalation time after a snooze: one hour later, as a UTC instant."""
    return _utc(due) + SNOOZE_BY


def may_acknowledge(status: str, *, owner_id: str, actor_id: str | None) -> None:
    _owner_only(owner_id, actor_id)
    if status not in _ACKNOWLEDGEABLE:
        raise InvalidTransition(f"an alert that is {status} cannot be acknowledged")


def may_snooze(status: str, *, owner_id: str, actor_id: str | None) -> None:
    _owner_only(owner_id, actor_id)
    if status not in _SNOOZABLE:
        raise InvalidTransition(f"an alert that is {status} cannot be snoozed")


def not_updated_check_times(changed_at: datetime) -> tuple[datetime, datetime]:
    """When a service that went not-updated at `changed_at` is checked again: at two and at four
    hours (domain-rules 4, NOT_UPDATED_HOURS)."""
    start = _utc(changed_at)
    first, second = sorted(NOT_UPDATED_HOURS)
    return start + timedelta(hours=first), start + timedelta(hours=second)
