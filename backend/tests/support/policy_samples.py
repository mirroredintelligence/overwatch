"""A policy factory and a Hypothesis strategy of valid tenant policies (TEN-021).

`policy(**overrides)` is the default policy with some fields replaced; `replace` runs the policy's
own checks, so an invalid override raises ValidationFailed at once. `policies()` draws every field
inside `FIELD_BOUNDS` and builds the ordered fields by construction, so every draw is a valid
policy. The bounds are TEN-006's; nothing here restates a number.
"""

from dataclasses import replace
from datetime import time, timedelta
from typing import Any

from hypothesis import strategies as st

from diucs.domain.codes import AlertKind
from diucs.domain.model.tenant_policy import (
    ALERT_NOT_UPDATED_CHOICES,
    DEFAULT_POLICY,
    FIELD_BOUNDS,
    MANY_CHANGES_COUNT_MAX,
    TenantPolicy,
)

# The unit of each duration bound: a bound is a whole number of minutes, hours or days.
_MINUTE = timedelta(minutes=1)
_HOUR = timedelta(hours=1)
_DAY = timedelta(days=1)


def policy(**overrides: Any) -> TenantPolicy:
    """The default policy with the given fields replaced. Invalid values raise ValidationFailed."""
    return replace(DEFAULT_POLICY, **overrides)


def _minutes(low: timedelta, high: timedelta) -> st.SearchStrategy[timedelta]:
    return st.integers(low // _MINUTE, high // _MINUTE).map(lambda n: _MINUTE * n)


def _minutes_above(floor: timedelta, high: timedelta) -> st.SearchStrategy[timedelta]:
    """Whole minutes from floor (inclusive) to high (inclusive), floor already in range."""
    return st.integers(floor // _MINUTE, high // _MINUTE).map(lambda n: _MINUTE * n)


def _count(field: str) -> st.SearchStrategy[int]:
    low, high = FIELD_BOUNDS[field]
    assert isinstance(low, int) and isinstance(high, int)
    return st.integers(low, high)


def _clock(field: str) -> st.SearchStrategy[time]:
    low, high = FIELD_BOUNDS[field]
    assert isinstance(low, time) and isinstance(high, time)
    low_minute = low.hour * 60 + low.minute
    high_minute = high.hour * 60 + high.minute
    return st.integers(low_minute, high_minute).map(lambda m: time(m // 60, m % 60))


@st.composite
def policies(draw: st.DrawFn) -> TenantPolicy:
    """A valid policy: every field inside its bounds, every cross-field rule satisfied."""
    reply_low, reply_high = FIELD_BOUNDS["reply_window"]
    assert isinstance(reply_low, timedelta) and isinstance(reply_high, timedelta)
    reply = draw(_minutes(reply_low, reply_high))

    # reminder >= reply; phone > reminder; escalate > phone (TenantPolicy.__post_init__).
    reminder_low, reminder_high = FIELD_BOUNDS["reminder_after"]
    assert isinstance(reminder_low, timedelta) and isinstance(reminder_high, timedelta)
    reminder = draw(_minutes_above(max(reminder_low, reply), reminder_high))

    phone_low, phone_high = FIELD_BOUNDS["phone_task_after"]
    assert isinstance(phone_low, timedelta) and isinstance(phone_high, timedelta)
    phone = draw(_minutes_above(max(phone_low, reminder + _MINUTE), phone_high))

    escalate_low, escalate_high = FIELD_BOUNDS["escalate_after"]
    assert isinstance(escalate_low, timedelta) and isinstance(escalate_high, timedelta)
    escalate = draw(_minutes_above(max(escalate_low, phone + _MINUTE), escalate_high))

    # Pressure: watch < high.
    watch = draw(_count("pressure_watch_from"))
    high_low, high_high = FIELD_BOUNDS["pressure_high_from"]
    assert isinstance(high_low, int) and isinstance(high_high, int)
    high = draw(st.integers(max(high_low, watch + 1), high_high))

    # Booking: the phone prompt comes before the booking reply window ends.
    booking_reply_low, booking_reply_high = FIELD_BOUNDS["booking_reply_window"]
    assert isinstance(booking_reply_low, timedelta)
    assert isinstance(booking_reply_high, timedelta)
    booking_reply = draw(_minutes(booking_reply_low, booking_reply_high))
    booking_prompt_low, booking_prompt_high = FIELD_BOUNDS["booking_phone_prompt_after"]
    assert isinstance(booking_prompt_low, timedelta)
    assert isinstance(booking_prompt_high, timedelta)
    booking_prompt = draw(
        _minutes_above(booking_prompt_low, min(booking_prompt_high, booking_reply - _MINUTE))
    )

    alert_kinds = draw(st.frozensets(st.sampled_from(list(AlertKind)), min_size=1))
    values: dict[str, object] = {
        "reply_window": reply,
        "reminder_after": reminder,
        "phone_task_after": phone,
        "escalate_after": escalate,
        "twice_a_day_second": draw(_clock("twice_a_day_second")),
        "stale_warning_after": draw(_minutes_by_hour("stale_warning_after")),
        "pressure_watch_from": watch,
        "pressure_high_from": high,
        "correction_window": draw(_minutes(*_bounds("correction_window"))),
        "max_consecutive_confirms": draw(_count("max_consecutive_confirms")),
        "many_changes_window": draw(_minutes(*_bounds("many_changes_window"))),
        "many_changes_count": draw(st.integers(2, MANY_CHANGES_COUNT_MAX)),
        "phoned_window": draw(_minutes(*_bounds("phoned_window"))),
        "group_window": draw(_minutes(*_bounds("group_window"))),
        "max_services_per_phone": draw(_count("max_services_per_phone")),
        "booking_reply_window": booking_reply,
        "booking_phone_prompt_after": booking_prompt,
        "withdrawal_escalate_after": draw(_minutes(*_bounds("withdrawal_escalate_after"))),
        "criteria_reminder_before": draw(_days("criteria_reminder_before")),
        "clinical_take_timeout": draw(_minutes(*_bounds("clinical_take_timeout"))),
        "reverify_every": draw(_days("reverify_every")),
        "critical_alert_kinds": alert_kinds,
        "alert_default_kinds": alert_kinds,
        "alert_default_not_updated_hours": draw(st.sampled_from(sorted(ALERT_NOT_UPDATED_CHOICES))),
    }
    return TenantPolicy(**values)  # type: ignore[arg-type]


def _bounds(field: str) -> tuple[timedelta, timedelta]:
    low, high = FIELD_BOUNDS[field]
    assert isinstance(low, timedelta) and isinstance(high, timedelta)
    return low, high


def _minutes_by_hour(field: str) -> st.SearchStrategy[timedelta]:
    low, high = _bounds(field)
    return st.integers(low // _HOUR, high // _HOUR).map(lambda n: _HOUR * n)


def _days(field: str) -> st.SearchStrategy[timedelta]:
    low, high = _bounds(field)
    return st.integers(low // _DAY, high // _DAY).map(lambda n: _DAY * n)

