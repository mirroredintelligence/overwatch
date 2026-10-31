"""The per-tenant policy: every threshold a tenant may set, its bounds and its defaults (TEN-006).

A `TenantPolicy` is a frozen value that the rule functions take as an explicit argument (audit B
section 6: explicit parameters, not ambient lookups), so the domain stays pure. The defaults equal
today's behaviour: `DEFAULT_POLICY` is the single-organisation system as it was before tenancy.
Each bound is an [ASSUMED] proposal unless audit F section 6.1 gives it (DEC-155 lists which); a
named constant holds every figure and none is a magic number in the checks below.

Fail closed: a value of the wrong exact type (a `bool` is not an `int`, a `float` is not a
`timedelta`), a value outside its range, and a set of thresholds that contradict each other are
all refused with `ValidationFailed` naming the field. Nothing falls back to a default.

The unit of a setting (minutes, hours, days, a count, a time of day, a set of codes) is the unit
an administrator sees and the registry stores (`tenant_settings.py`). The policy holds native
types; `POLICY_FIELDS` is the one table that says which unit and which setting key each field has.

Standard library and `diucs.domain` only.
"""

from dataclasses import dataclass
from datetime import time, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final, cast

from diucs.domain.codes import AlertKind
from diucs.domain.errors import ValidationFailed

type SettingValue = int | str | bool | time | frozenset[str]

# ---------------------------------------------------------------- defaults and bounds
# Defaults equal the module constants of the rule modules today (a test compares them). Bounds
# marked [ASSUMED] are proposals (audit F section 6.1 gives none): a change to any of them needs a
# new decision (DEC-007, DEC-155).

REPLY_WINDOW_DEFAULT: Final = timedelta(minutes=30)
REPLY_WINDOW_MIN: Final = timedelta(minutes=15)
REPLY_WINDOW_MAX: Final = timedelta(minutes=60)

REMINDER_AFTER_DEFAULT: Final = timedelta(minutes=30)
REMINDER_AFTER_MIN: Final = timedelta(minutes=15)  # [ASSUMED]
REMINDER_AFTER_MAX: Final = timedelta(minutes=90)  # [ASSUMED]

PHONE_TASK_AFTER_DEFAULT: Final = timedelta(minutes=60)
PHONE_TASK_AFTER_MIN: Final = timedelta(minutes=30)  # [ASSUMED]
PHONE_TASK_AFTER_MAX: Final = timedelta(minutes=180)  # [ASSUMED]

ESCALATE_AFTER_DEFAULT: Final = timedelta(minutes=90)
ESCALATE_AFTER_MIN: Final = timedelta(minutes=45)  # [ASSUMED]
ESCALATE_AFTER_MAX: Final = timedelta(minutes=360)  # [ASSUMED]

TWICE_A_DAY_SECOND_DEFAULT: Final = time(14, 0)
TWICE_A_DAY_SECOND_MIN: Final = time(12, 0)  # [ASSUMED]
TWICE_A_DAY_SECOND_MAX: Final = time(16, 0)  # [ASSUMED]

STALE_WARNING_DEFAULT: Final = timedelta(hours=2)
STALE_WARNING_MIN: Final = timedelta(hours=1)
STALE_WARNING_MAX: Final = timedelta(hours=4)

PRESSURE_WATCH_DEFAULT: Final = 3
PRESSURE_WATCH_MIN: Final = 1  # [ASSUMED]
PRESSURE_WATCH_MAX: Final = 50  # [ASSUMED]

PRESSURE_HIGH_DEFAULT: Final = 5
PRESSURE_HIGH_MIN: Final = 2  # [ASSUMED]
PRESSURE_HIGH_MAX: Final = 100  # [ASSUMED]

CORRECTION_WINDOW_DEFAULT: Final = timedelta(minutes=15)
CORRECTION_WINDOW_MIN: Final = timedelta(minutes=5)
CORRECTION_WINDOW_MAX: Final = timedelta(minutes=30)

MAX_CONFIRMS_DEFAULT: Final = 2
MAX_CONFIRMS_MIN: Final = 1
MAX_CONFIRMS_MAX: Final = 3

MANY_CHANGES_WINDOW_DEFAULT: Final = timedelta(minutes=5)
MANY_CHANGES_WINDOW_MIN: Final = timedelta(minutes=1)  # [ASSUMED]
MANY_CHANGES_WINDOW_MAX: Final = timedelta(minutes=30)  # [ASSUMED]

MANY_CHANGES_COUNT_DEFAULT: Final = 3
MANY_CHANGES_COUNT_MIN: Final = 2  # [ASSUMED]
MANY_CHANGES_COUNT_MAX: Final = 10  # [ASSUMED]

PHONED_WINDOW_DEFAULT: Final = timedelta(minutes=60)
PHONED_WINDOW_MIN: Final = timedelta(minutes=15)  # [ASSUMED]
PHONED_WINDOW_MAX: Final = timedelta(minutes=240)  # [ASSUMED]

GROUP_WINDOW_DEFAULT: Final = timedelta(minutes=10)
GROUP_WINDOW_MIN: Final = timedelta(minutes=5)
GROUP_WINDOW_MAX: Final = timedelta(minutes=20)

MAX_SERVICES_PER_PHONE_DEFAULT: Final = 3
MAX_SERVICES_PER_PHONE_MIN: Final = 2
MAX_SERVICES_PER_PHONE_MAX: Final = 6

BOOKING_REPLY_WINDOW_DEFAULT: Final = timedelta(minutes=10)
BOOKING_REPLY_WINDOW_MIN: Final = timedelta(minutes=5)  # [ASSUMED]
BOOKING_REPLY_WINDOW_MAX: Final = timedelta(minutes=30)  # [ASSUMED]

BOOKING_PROMPT_DEFAULT: Final = timedelta(minutes=5)
BOOKING_PROMPT_MIN: Final = timedelta(minutes=2)  # [ASSUMED]
BOOKING_PROMPT_MAX: Final = timedelta(minutes=15)  # [ASSUMED]

# domain-rules.md, bookings: after a withdrawal, if nobody acts within 10 minutes the shift lead
# is alerted.
WITHDRAWAL_ESCALATE_DEFAULT: Final = timedelta(minutes=10)
WITHDRAWAL_ESCALATE_MIN: Final = timedelta(minutes=5)  # [ASSUMED]
WITHDRAWAL_ESCALATE_MAX: Final = timedelta(minutes=30)  # [ASSUMED]

CRITERIA_REMINDER_DEFAULT: Final = timedelta(days=14)
CRITERIA_REMINDER_MIN: Final = timedelta(days=7)
CRITERIA_REMINDER_MAX: Final = timedelta(days=30)

CLINICAL_TAKE_DEFAULT: Final = timedelta(minutes=10)
CLINICAL_TAKE_MIN: Final = timedelta(minutes=5)
CLINICAL_TAKE_MAX: Final = timedelta(minutes=20)

# A tenant may only shorten the re-verification period: the default is the maximum.
REVERIFY_DEFAULT: Final = timedelta(days=30)
REVERIFY_MIN: Final = timedelta(days=7)
REVERIFY_MAX: Final = timedelta(days=30)

CRITICAL_ALERT_KINDS_DEFAULT: Final = frozenset(
    {AlertKind.SERVICE_CLOSED, AlertKind.SYSTEM_PRESSURE}
)
ALERT_DEFAULT_KINDS_DEFAULT: Final = frozenset(AlertKind)
ALERT_KIND_VALUES: Final = frozenset(kind.value for kind in AlertKind)

ALERT_NOT_UPDATED_DEFAULT: Final = 2
ALERT_NOT_UPDATED_CHOICES: Final = frozenset({2, 4})

OUTSIDE_RANGE_MESSAGE: Final = "is outside the allowed range"
WRONG_TYPE_MESSAGE: Final = "has the wrong type"
WHOLE_UNITS_MESSAGE: Final = "must be a whole number of its unit"
NOT_ALLOWED_VALUE_MESSAGE: Final = "is not an allowed value"


# ---------------------------------------------------------------- the field table


class Shape(StrEnum):
    """What a policy field holds natively."""

    DURATION = "duration"
    COUNT = "count"
    TIME_OF_DAY = "time-of-day"
    CODES = "codes"
    CHOICE = "choice"


UNIT_MINUTES: Final = "minutes"
UNIT_HOURS: Final = "hours"
UNIT_DAYS: Final = "days"
UNIT_COUNT: Final = "count"
UNIT_TIME_OF_DAY: Final = "time-of-day"
UNIT_CODES: Final = "codes"

_DURATION_UNITS: Final = {
    UNIT_MINUTES: timedelta(minutes=1),
    UNIT_HOURS: timedelta(hours=1),
    UNIT_DAYS: timedelta(days=1),
}


@dataclass(frozen=True, slots=True)
class PolicyField:
    """One row of the policy table: the field, the setting key that sets it and its unit."""

    name: str
    key: str
    shape: Shape
    unit: str


_D, _N, _T, _C, _H = (
    Shape.DURATION,
    Shape.COUNT,
    Shape.TIME_OF_DAY,
    Shape.CODES,
    Shape.CHOICE,
)

# In the order of the prompt's table. The setting keys are the identity shown to administrators
# and stored on setting rows (TEN-026): do not rename.
POLICY_FIELDS: Final = (
    PolicyField("reply_window", "replyWindowMinutes", _D, UNIT_MINUTES),
    PolicyField("reminder_after", "reminderAfterMinutes", _D, UNIT_MINUTES),
    PolicyField("phone_task_after", "phoneTaskAfterMinutes", _D, UNIT_MINUTES),
    PolicyField("escalate_after", "escalateAfterMinutes", _D, UNIT_MINUTES),
    PolicyField("twice_a_day_second", "twiceADaySecondTime", _T, UNIT_TIME_OF_DAY),
    PolicyField("stale_warning_after", "staleWarningHours", _D, UNIT_HOURS),
    PolicyField("pressure_watch_from", "pressureWatchFrom", _N, UNIT_COUNT),
    PolicyField("pressure_high_from", "pressureHighFrom", _N, UNIT_COUNT),
    PolicyField("correction_window", "correctionWindowMinutes", _D, UNIT_MINUTES),
    PolicyField("max_consecutive_confirms", "maxConsecutiveConfirms", _N, UNIT_COUNT),
    PolicyField("many_changes_window", "manyChangesWindowMinutes", _D, UNIT_MINUTES),
    PolicyField("many_changes_count", "manyChangesCount", _N, UNIT_COUNT),
    PolicyField("phoned_window", "phonedWindowMinutes", _D, UNIT_MINUTES),
    PolicyField("group_window", "groupWindowMinutes", _D, UNIT_MINUTES),
    PolicyField("max_services_per_phone", "maxServicesPerPhoneWarn", _N, UNIT_COUNT),
    PolicyField("booking_reply_window", "bookingReplyWindowMinutes", _D, UNIT_MINUTES),
    PolicyField("booking_phone_prompt_after", "bookingPhonePromptMinutes", _D, UNIT_MINUTES),
    PolicyField("withdrawal_escalate_after", "withdrawalEscalateMinutes", _D, UNIT_MINUTES),
    PolicyField("criteria_reminder_before", "criteriaReminderDays", _D, UNIT_DAYS),
    PolicyField("clinical_take_timeout", "clinicalTakeTimeoutMinutes", _D, UNIT_MINUTES),
    PolicyField("reverify_every", "reverifyEveryDays", _D, UNIT_DAYS),
    PolicyField("critical_alert_kinds", "criticalAlertKinds", _C, UNIT_CODES),
    PolicyField("alert_default_kinds", "alertDefaultKinds", _C, UNIT_CODES),
    PolicyField("alert_default_not_updated_hours", "alertDefaultNotUpdatedHours", _H, UNIT_HOURS),
)
POLICY_FIELD_BY_KEY: Final = MappingProxyType({field.key: field for field in POLICY_FIELDS})

# Inclusive native-type minimum and maximum of every field that has a numeric range. The three
# set-valued fields have none: they are checked against their allowed values.
FIELD_BOUNDS: Final[MappingProxyType[str, tuple[object, object]]] = MappingProxyType(
    {
        "reply_window": (REPLY_WINDOW_MIN, REPLY_WINDOW_MAX),
        "reminder_after": (REMINDER_AFTER_MIN, REMINDER_AFTER_MAX),
        "phone_task_after": (PHONE_TASK_AFTER_MIN, PHONE_TASK_AFTER_MAX),
        "escalate_after": (ESCALATE_AFTER_MIN, ESCALATE_AFTER_MAX),
        "twice_a_day_second": (TWICE_A_DAY_SECOND_MIN, TWICE_A_DAY_SECOND_MAX),
        "stale_warning_after": (STALE_WARNING_MIN, STALE_WARNING_MAX),
        "pressure_watch_from": (PRESSURE_WATCH_MIN, PRESSURE_WATCH_MAX),
        "pressure_high_from": (PRESSURE_HIGH_MIN, PRESSURE_HIGH_MAX),
        "correction_window": (CORRECTION_WINDOW_MIN, CORRECTION_WINDOW_MAX),
        "max_consecutive_confirms": (MAX_CONFIRMS_MIN, MAX_CONFIRMS_MAX),
        "many_changes_window": (MANY_CHANGES_WINDOW_MIN, MANY_CHANGES_WINDOW_MAX),
        "many_changes_count": (MANY_CHANGES_COUNT_MIN, MANY_CHANGES_COUNT_MAX),
        "phoned_window": (PHONED_WINDOW_MIN, PHONED_WINDOW_MAX),
        "group_window": (GROUP_WINDOW_MIN, GROUP_WINDOW_MAX),
        "max_services_per_phone": (MAX_SERVICES_PER_PHONE_MIN, MAX_SERVICES_PER_PHONE_MAX),
        "booking_reply_window": (BOOKING_REPLY_WINDOW_MIN, BOOKING_REPLY_WINDOW_MAX),
        "booking_phone_prompt_after": (BOOKING_PROMPT_MIN, BOOKING_PROMPT_MAX),
        "withdrawal_escalate_after": (WITHDRAWAL_ESCALATE_MIN, WITHDRAWAL_ESCALATE_MAX),
        "criteria_reminder_before": (CRITERIA_REMINDER_MIN, CRITERIA_REMINDER_MAX),
        "clinical_take_timeout": (CLINICAL_TAKE_MIN, CLINICAL_TAKE_MAX),
        "reverify_every": (REVERIFY_MIN, REVERIFY_MAX),
    }
)


# ---------------------------------------------------------------- unit conversion


def to_setting_value(field: PolicyField, value: object) -> SettingValue:
    """The unit value of a native value: minutes, hours or days as a whole number, the other
    shapes as they are, codes as plain text. The inverse of `from_setting_value`."""
    if field.shape is Shape.DURATION:
        return cast(timedelta, value) // _DURATION_UNITS[field.unit]
    if field.shape is Shape.CODES:
        return frozenset(member.value for member in cast(frozenset[AlertKind], value))
    return cast(SettingValue, value)


def from_setting_value(field: PolicyField, value: SettingValue) -> object:
    """The native value of a unit value that has already been validated."""
    if field.shape is Shape.DURATION:
        return _DURATION_UNITS[field.unit] * cast(int, value)
    if field.shape is Shape.CODES:
        return frozenset(AlertKind(code) for code in cast(frozenset[str], value))
    return value


# ---------------------------------------------------------------- the policy


def _check_duration(field: PolicyField, value: object) -> None:
    if type(value) is not timedelta:
        raise ValidationFailed(field.name, WRONG_TYPE_MESSAGE)
    if value % _DURATION_UNITS[field.unit]:
        raise ValidationFailed(field.name, WHOLE_UNITS_MESSAGE)


def _check_time_of_day(field: PolicyField, value: object) -> None:
    if type(value) is not time or value.tzinfo is not None:
        raise ValidationFailed(field.name, WRONG_TYPE_MESSAGE)
    if value.second or value.microsecond:
        raise ValidationFailed(field.name, WHOLE_UNITS_MESSAGE)


def _check_count(field: PolicyField, value: object) -> None:
    if type(value) is not int:
        raise ValidationFailed(field.name, WRONG_TYPE_MESSAGE)


def _check_codes(field: PolicyField, value: object) -> None:
    if type(value) is not frozenset:
        raise ValidationFailed(field.name, WRONG_TYPE_MESSAGE)
    if not value or any(type(member) is not AlertKind for member in value):
        raise ValidationFailed(field.name, NOT_ALLOWED_VALUE_MESSAGE)


def _check_choice(field: PolicyField, value: object) -> None:
    if type(value) is not int:
        raise ValidationFailed(field.name, WRONG_TYPE_MESSAGE)
    if value not in ALERT_NOT_UPDATED_CHOICES:
        raise ValidationFailed(field.name, NOT_ALLOWED_VALUE_MESSAGE)


def _check_range(field: PolicyField, value: Any) -> None:
    low, high = FIELD_BOUNDS[field.name]
    if not low <= value <= high:
        raise ValidationFailed(field.name, OUTSIDE_RANGE_MESSAGE)


def _check_field(field: PolicyField, value: object) -> None:
    if field.shape is Shape.DURATION:
        _check_duration(field, value)
    elif field.shape is Shape.TIME_OF_DAY:
        _check_time_of_day(field, value)
    elif field.shape is Shape.COUNT:
        _check_count(field, value)
    elif field.shape is Shape.CODES:
        _check_codes(field, value)
    else:
        _check_choice(field, value)
    if field.name in FIELD_BOUNDS:
        _check_range(field, value)


@dataclass(frozen=True, slots=True)
class TenantPolicy:
    """Every threshold a tenant may set. The field defaults equal today's behaviour."""

    reply_window: timedelta = REPLY_WINDOW_DEFAULT
    reminder_after: timedelta = REMINDER_AFTER_DEFAULT
    phone_task_after: timedelta = PHONE_TASK_AFTER_DEFAULT
    escalate_after: timedelta = ESCALATE_AFTER_DEFAULT
    twice_a_day_second: time = TWICE_A_DAY_SECOND_DEFAULT
    stale_warning_after: timedelta = STALE_WARNING_DEFAULT
    pressure_watch_from: int = PRESSURE_WATCH_DEFAULT
    pressure_high_from: int = PRESSURE_HIGH_DEFAULT
    correction_window: timedelta = CORRECTION_WINDOW_DEFAULT
    max_consecutive_confirms: int = MAX_CONFIRMS_DEFAULT
    many_changes_window: timedelta = MANY_CHANGES_WINDOW_DEFAULT
    many_changes_count: int = MANY_CHANGES_COUNT_DEFAULT
    phoned_window: timedelta = PHONED_WINDOW_DEFAULT
    group_window: timedelta = GROUP_WINDOW_DEFAULT
    max_services_per_phone: int = MAX_SERVICES_PER_PHONE_DEFAULT
    booking_reply_window: timedelta = BOOKING_REPLY_WINDOW_DEFAULT
    booking_phone_prompt_after: timedelta = BOOKING_PROMPT_DEFAULT
    withdrawal_escalate_after: timedelta = WITHDRAWAL_ESCALATE_DEFAULT
    criteria_reminder_before: timedelta = CRITERIA_REMINDER_DEFAULT
    clinical_take_timeout: timedelta = CLINICAL_TAKE_DEFAULT
    reverify_every: timedelta = REVERIFY_DEFAULT
    critical_alert_kinds: frozenset[AlertKind] = CRITICAL_ALERT_KINDS_DEFAULT
    alert_default_kinds: frozenset[AlertKind] = ALERT_DEFAULT_KINDS_DEFAULT
    alert_default_not_updated_hours: int = ALERT_NOT_UPDATED_DEFAULT

    def __post_init__(self) -> None:
        for field in POLICY_FIELDS:
            _check_field(field, getattr(self, field.name))
        # Each comparison is its own refusal with its own message, so a failure names what to fix.
        if self.reply_window > self.reminder_after:
            raise ValidationFailed("reminder_after", "must not be shorter than the reply window")
        if self.reminder_after >= self.phone_task_after:
            raise ValidationFailed("phone_task_after", "must be after the reminder")
        if self.phone_task_after >= self.escalate_after:
            raise ValidationFailed("escalate_after", "must be after the phone task")
        if self.pressure_watch_from >= self.pressure_high_from:
            raise ValidationFailed("pressure_high_from", "must be above the watch level")
        if self.booking_phone_prompt_after >= self.booking_reply_window:
            raise ValidationFailed(
                "booking_phone_prompt_after", "must be before the booking reply window ends"
            )

    def as_settings(self) -> dict[str, SettingValue]:
        """Every setting key with its unit value: the inverse of `policy_from_settings`."""
        return {
            field.key: to_setting_value(field, getattr(self, field.name)) for field in POLICY_FIELDS
        }


DEFAULT_POLICY: Final = TenantPolicy()


def require_policy(value: object) -> TenantPolicy:
    """Return the policy, or refuse anything that is not exactly a `TenantPolicy`. The rule modules
    call this first (TEN-021, TEN-064): a subclass, a mapping of settings or None is a bug."""
    if type(value) is not TenantPolicy:
        raise TypeError("a TenantPolicy is required")
    return value
