"""Tenant settings: the registry, bounds, defaults, approvals and wording text (TEN-006).

Rules: docs/delivery/decisions.md DEC-155, the task prompt rules 5, 6 and 10. The golden table
below is typed out from the prompt, not read from the registry, so a changed bound is caught.
"""

import contextlib
import dataclasses
import types
from datetime import time, timedelta
from typing import Any

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from diucs.domain.codes import AlertKind
from diucs.domain.errors import NotAllowed, ValidationFailed
from diucs.domain.model.tenant_policy import (
    DEFAULT_POLICY,
    FIELD_BOUNDS,
    TenantPolicy,
    require_policy,
)
from diucs.domain.rules import (
    alerts,
    booking_rules,
    clinical_queue,
    criteria_workflow,
    freshness,
    identity_policy,
    multi_service,
    pressure,
    reply_policy,
    report_flags,
    schedule,
)
from diucs.domain.rules.tenant_settings import (
    SETTING_SPECS,
    SafetyClass,
    SettingKind,
    SettingScope,
    SettingSpec,
    approvals_required,
    changed_keys,
    check_approvals,
    check_tenant_text,
    clinical_keys,
    policy_from_settings,
    spec_for,
    validate_settings,
    validate_value,
)

ALL_KINDS = sorted(kind.value for kind in AlertKind)

# field, key, unit, default, minimum, maximum, class, scope. Numbers are in the unit of the key.
GOLDEN: tuple[tuple[str, str, str, Any, Any, Any, str, str], ...] = (
    ("reply_window", "replyWindowMinutes", "minutes", 30, 15, 60, "clinical", "tenant"),
    ("reminder_after", "reminderAfterMinutes", "minutes", 30, 15, 90, "clinical", "tenant"),
    ("phone_task_after", "phoneTaskAfterMinutes", "minutes", 60, 30, 180, "clinical", "tenant"),
    ("escalate_after", "escalateAfterMinutes", "minutes", 90, 45, 360, "clinical", "tenant"),
    (
        "twice_a_day_second",
        "twiceADaySecondTime",
        "time-of-day",
        time(14, 0),
        time(12, 0),
        time(16, 0),
        "clinical",
        "tenant",
    ),
    ("stale_warning_after", "staleWarningHours", "hours", 2, 1, 4, "clinical", "tenant"),
    ("pressure_watch_from", "pressureWatchFrom", "count", 3, 1, 50, "clinical", "both"),
    ("pressure_high_from", "pressureHighFrom", "count", 5, 2, 100, "clinical", "both"),
    ("correction_window", "correctionWindowMinutes", "minutes", 15, 5, 30, "clinical", "tenant"),
    ("max_consecutive_confirms", "maxConsecutiveConfirms", "count", 2, 1, 3, "clinical", "tenant"),
    ("many_changes_window", "manyChangesWindowMinutes", "minutes", 5, 1, 30, "clinical", "tenant"),
    ("many_changes_count", "manyChangesCount", "count", 3, 2, 10, "clinical", "tenant"),
    ("phoned_window", "phonedWindowMinutes", "minutes", 60, 15, 240, "clinical", "tenant"),
    ("group_window", "groupWindowMinutes", "minutes", 10, 5, 20, "clinical", "tenant"),
    ("max_services_per_phone", "maxServicesPerPhoneWarn", "count", 3, 2, 6, "clinical", "tenant"),
    (
        "booking_reply_window",
        "bookingReplyWindowMinutes",
        "minutes",
        10,
        5,
        30,
        "clinical",
        "tenant",
    ),
    (
        "booking_phone_prompt_after",
        "bookingPhonePromptMinutes",
        "minutes",
        5,
        2,
        15,
        "clinical",
        "tenant",
    ),
    (
        "withdrawal_escalate_after",
        "withdrawalEscalateMinutes",
        "minutes",
        10,
        5,
        30,
        "clinical",
        "tenant",
    ),
    ("criteria_reminder_before", "criteriaReminderDays", "days", 14, 7, 30, "clinical", "tenant"),
    (
        "clinical_take_timeout",
        "clinicalTakeTimeoutMinutes",
        "minutes",
        10,
        5,
        20,
        "clinical",
        "tenant",
    ),
    ("reverify_every", "reverifyEveryDays", "days", 30, 7, 30, "clinical", "tenant"),
)
# The three rows that have no numeric range: field, key, unit, class, scope.
SET_ROWS = (
    ("critical_alert_kinds", "criticalAlertKinds", "codes", "clinical", "tenant"),
    ("alert_default_kinds", "alertDefaultKinds", "codes", "operational", "tenant"),
    (
        "alert_default_not_updated_hours",
        "alertDefaultNotUpdatedHours",
        "hours",
        "operational",
        "tenant",
    ),
)
WORDING_ROWS = (
    ("systemName", "system_name", 60),
    ("referralSystemName", "referral_system_name", 40),
    ("coordinationTeamName", "coordination_team_name", 60),
)
POLICY_FIELD_ORDER = [row[0] for row in GOLDEN[:-1]] + ["reverify_every"]
POLICY_FIELD_ORDER += [row[0] for row in SET_ROWS]

SAMPLE_VALUES = ("Dorset urgent care capacity", "SystmOne", "The SPOA shift lead")
CANARY = "canary-tenant-ref"


def native(unit: str, value: Any) -> Any:
    """A unit value as the policy holds it."""
    if unit == "minutes":
        return timedelta(minutes=value)
    if unit == "hours":
        return timedelta(hours=value)
    if unit == "days":
        return timedelta(days=value)
    return value


def one_below(unit: str, value: Any) -> Any:
    if unit == "time-of-day":
        return time(value.hour - 1, 59)
    return value - 1


def one_above(unit: str, value: Any) -> Any:
    if unit == "time-of-day":
        return time(value.hour, 1)
    return value + 1


def settings_at(index: int) -> dict[str, Any]:
    """Every golden row at its minimum (index 4) or maximum (index 5), in its own unit."""
    return {row[1]: row[index] for row in GOLDEN}


def policy_at(index: int) -> TenantPolicy:
    return dataclasses.replace(
        DEFAULT_POLICY, **{row[0]: native(row[2], row[index]) for row in GOLDEN}
    )


# ---------------------------------------------------------------- 9. the golden table


def test_the_table_has_24_policy_rows_and_the_registry_has_27_entries() -> None:
    assert len(GOLDEN) + len(SET_ROWS) == 24
    assert len(SETTING_SPECS) == 27
    assert [f.name for f in dataclasses.fields(TenantPolicy)] == POLICY_FIELD_ORDER
    assert [spec.key for spec in SETTING_SPECS] == (
        [row[1] for row in GOLDEN] + [row[1] for row in SET_ROWS] + [row[0] for row in WORDING_ROWS]
    )
    assert len({spec.key for spec in SETTING_SPECS}) == 27


@pytest.mark.parametrize("row", GOLDEN, ids=[row[1] for row in GOLDEN])
def test_each_golden_row_has_its_default_class_scope_unit_and_range(row: tuple[Any, ...]) -> None:
    field, key, unit, default, minimum, maximum, safety, scope = row
    assert getattr(DEFAULT_POLICY, field) == native(unit, default)
    spec = spec_for(key)
    assert spec.policy_field == field
    assert spec.unit == unit
    assert spec.default == default
    assert spec.minimum == minimum
    assert spec.maximum == maximum
    assert spec.safety_class.value == safety
    assert spec.scope.value == scope
    assert spec.required_for_activation is False
    assert FIELD_BOUNDS[field] == (native(unit, minimum), native(unit, maximum))


@pytest.mark.parametrize("row", GOLDEN, ids=[row[1] for row in GOLDEN])
def test_each_golden_row_accepts_both_ends_and_refuses_one_unit_outside(
    row: tuple[Any, ...],
) -> None:
    field, key, unit, _default, minimum, maximum, _safety, _scope = row
    spec = spec_for(key)
    assert validate_value(spec, minimum) == minimum
    assert validate_value(spec, maximum) == maximum
    for outside in (one_below(unit, minimum), one_above(unit, maximum)):
        with pytest.raises(ValidationFailed) as refused:
            validate_value(spec, outside)
        assert refused.value.field == key
    # The policy checks the same ends. All minimums, and all maximums, are a legal policy.
    low, high = policy_at(4), policy_at(5)
    assert getattr(low, field) == native(unit, minimum)
    assert getattr(high, field) == native(unit, maximum)
    for outside, base in ((one_below(unit, minimum), low), (one_above(unit, maximum), high)):
        with pytest.raises(ValidationFailed) as refused:
            dataclasses.replace(base, **{field: native(unit, outside)})
        assert refused.value.message == "is outside the allowed range"
        assert refused.value.field == field


def test_the_set_rows_have_their_class_scope_and_unit() -> None:
    for field, key, unit, safety, scope in SET_ROWS:
        spec = spec_for(key)
        assert (spec.policy_field, spec.unit) == (field, unit)
        assert (spec.safety_class.value, spec.scope.value) == (safety, scope)
        assert spec.required_for_activation is False
    assert spec_for("criticalAlertKinds").default == frozenset(
        {"service-closed", "system-pressure"}
    )
    assert spec_for("alertDefaultKinds").default == frozenset(ALL_KINDS)
    assert spec_for("criticalAlertKinds").allowed == frozenset(ALL_KINDS)
    assert spec_for("alertDefaultNotUpdatedHours").default == 2
    assert spec_for("alertDefaultNotUpdatedHours").choices == frozenset({2, 4})
    assert spec_for("alertDefaultNotUpdatedHours").kind is SettingKind.INT
    assert spec_for("criticalAlertKinds").kind is SettingKind.CODES


def test_the_wording_rows_are_required_for_activation_and_have_no_default() -> None:
    for key, _field, limit in WORDING_ROWS:
        spec = spec_for(key)
        assert spec.kind is SettingKind.TEXT
        assert spec.policy_field is None
        assert spec.default is None
        assert spec.minimum == 1
        assert spec.maximum == limit
        assert spec.required_for_activation is True
        assert spec.safety_class is SafetyClass.OPERATIONAL
        assert spec.scope is SettingScope.TENANT


def test_field_bounds_is_read_only_and_holds_the_21_ranges() -> None:
    assert len(FIELD_BOUNDS) == 21
    with pytest.raises(TypeError):
        FIELD_BOUNDS["reply_window"] = (timedelta(0), timedelta(0))  # type: ignore[index]
    assert FIELD_BOUNDS["twice_a_day_second"] == (time(12, 0), time(16, 0))
    assert FIELD_BOUNDS["pressure_high_from"] == (2, 100)


# ---------------------------------------------------------------- 10. defaults equal today


def test_the_default_policy_equals_the_module_constants_of_the_rules() -> None:
    d = DEFAULT_POLICY
    assert d.reply_window == schedule.REPLY_WINDOW
    assert d.reminder_after == schedule.REMINDER_AFTER
    assert d.phone_task_after == schedule.PHONE_TASK_AFTER
    assert d.escalate_after == schedule.ESCALATE_AFTER
    assert d.twice_a_day_second == schedule.TWICE_A_DAY_SECOND
    assert d.stale_warning_after == freshness.STALE_WARNING_AFTER
    assert d.pressure_watch_from == pressure.WATCH_FROM
    assert d.pressure_high_from == pressure.HIGH_FROM
    assert d.correction_window == reply_policy.CORRECTION_WINDOW
    assert d.max_consecutive_confirms == reply_policy.MAX_CONSECUTIVE_CONFIRMS
    assert d.many_changes_window == report_flags.MANY_CHANGES_WINDOW
    assert d.many_changes_count == report_flags.MANY_CHANGES_COUNT
    assert d.phoned_window == report_flags.PHONED_WINDOW
    assert d.group_window == multi_service.GROUP_WINDOW
    assert d.max_services_per_phone == multi_service.MAX_SERVICES_PER_PHONE
    assert d.booking_reply_window == booking_rules.BOOKING_REPLY_WINDOW
    assert d.booking_phone_prompt_after == booking_rules.PHONE_PROMPT_AFTER
    assert d.criteria_reminder_before == criteria_workflow.REVIEW_REMINDER_BEFORE
    assert d.clinical_take_timeout == clinical_queue.TAKE_TIMEOUT
    assert d.reverify_every == identity_policy.REVERIFY_EVERY
    assert d.critical_alert_kinds == alerts.CRITICAL_KINDS
    assert d.alert_default_kinds == alerts.default_preferences().kinds
    assert d.alert_default_not_updated_hours == alerts.default_preferences().not_updated_hours
    assert spec_for("alertDefaultNotUpdatedHours").choices == alerts.NOT_UPDATED_HOURS


def test_the_default_policy_equals_literals_so_the_test_survives_the_rules_reading_it() -> None:
    d = DEFAULT_POLICY
    assert d.reply_window == timedelta(minutes=30)
    assert d.reminder_after == timedelta(minutes=30)
    assert d.phone_task_after == timedelta(minutes=60)
    assert d.escalate_after == timedelta(minutes=90)
    assert d.twice_a_day_second == time(14, 0)
    assert d.stale_warning_after == timedelta(hours=2)
    assert (d.pressure_watch_from, d.pressure_high_from) == (3, 5)
    assert d.correction_window == timedelta(minutes=15)
    assert d.max_consecutive_confirms == 2
    assert d.many_changes_window == timedelta(minutes=5)
    assert d.many_changes_count == 3
    assert d.phoned_window == timedelta(minutes=60)
    assert d.group_window == timedelta(minutes=10)
    assert d.max_services_per_phone == 3
    assert d.booking_reply_window == timedelta(minutes=10)
    assert d.booking_phone_prompt_after == timedelta(minutes=5)
    assert d.withdrawal_escalate_after == timedelta(minutes=10)
    assert d.criteria_reminder_before == timedelta(days=14)
    assert d.clinical_take_timeout == timedelta(minutes=10)
    assert d.reverify_every == timedelta(days=30)
    assert d.critical_alert_kinds == frozenset(
        {AlertKind.SERVICE_CLOSED, AlertKind.SYSTEM_PRESSURE}
    )
    assert d.alert_default_kinds == frozenset(AlertKind)
    assert d.alert_default_not_updated_hours == 2


# ---------------------------------------------------------------- 11. from settings


def test_no_overrides_is_the_default_policy() -> None:
    assert policy_from_settings({}) == DEFAULT_POLICY


def test_an_override_changes_that_field_and_leaves_the_others() -> None:
    policy = policy_from_settings({"replyWindowMinutes": 20, "reminderAfterMinutes": 25})
    assert policy.reply_window == timedelta(minutes=20)
    assert policy.reminder_after == timedelta(minutes=25)
    expected = dataclasses.replace(
        DEFAULT_POLICY, reply_window=timedelta(minutes=20), reminder_after=timedelta(minutes=25)
    )
    assert policy == expected


def test_each_unit_converts_to_its_native_type() -> None:
    policy = policy_from_settings(
        {
            "staleWarningHours": 3,
            "criteriaReminderDays": 21,
            "twiceADaySecondTime": time(15, 30),
            "criticalAlertKinds": frozenset({"over-capacity"}),
            "alertDefaultNotUpdatedHours": 4,
        }
    )
    assert policy.stale_warning_after == timedelta(hours=3)
    assert policy.criteria_reminder_before == timedelta(days=21)
    assert policy.twice_a_day_second == time(15, 30)
    assert policy.critical_alert_kinds == frozenset({AlertKind.OVER_CAPACITY})
    assert all(type(kind) is AlertKind for kind in policy.critical_alert_kinds)
    assert policy.alert_default_not_updated_hours == 4


def test_an_unknown_key_is_refused_not_ignored() -> None:
    with pytest.raises(ValidationFailed) as refused:
        policy_from_settings({"replyWindowMinute": 20})
    assert refused.value.field == "key"
    assert refused.value.message == "not a tenant setting"


@pytest.mark.parametrize("bad_key", [1, None, "", "systemname"])
def test_a_key_that_is_not_a_known_string_is_refused(bad_key: Any) -> None:
    with pytest.raises(ValidationFailed):
        policy_from_settings({bad_key: 20})


@pytest.mark.parametrize(
    "not_a_mapping", [None, [("replyWindowMinutes", 20)], "replyWindowMinutes"]
)
def test_settings_must_be_a_mapping(not_a_mapping: Any) -> None:
    with pytest.raises(ValidationFailed):
        policy_from_settings(not_a_mapping)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("maxConsecutiveConfirms", True),
        ("replyWindowMinutes", 30.0),
        ("replyWindowMinutes", "30"),
        ("replyWindowMinutes", None),
        ("replyWindowMinutes", timedelta(minutes=30)),
        ("twiceADaySecondTime", time(14, 0, 5)),
        ("twiceADaySecondTime", time(14, 0, 0, 1)),
        ("twiceADaySecondTime", 14),
        ("twiceADaySecondTime", "14:00"),
        ("criticalAlertKinds", {"service-closed"}),
        ("criticalAlertKinds", ["service-closed"]),
        ("criticalAlertKinds", "service-closed"),
        ("criticalAlertKinds", frozenset()),
        ("criticalAlertKinds", frozenset({"service-closed", "not-a-kind"})),
        ("criticalAlertKinds", frozenset({AlertKind.SERVICE_CLOSED})),
        ("criticalAlertKinds", frozenset({1})),
        ("alertDefaultKinds", frozenset()),
        ("alertDefaultNotUpdatedHours", 3),
        ("alertDefaultNotUpdatedHours", True),
        ("alertDefaultNotUpdatedHours", 2.0),
    ],
)
def test_a_value_of_the_wrong_type_or_outside_its_choices_is_refused(key: str, value: Any) -> None:
    with pytest.raises(ValidationFailed) as refused:
        policy_from_settings({key: value})
    assert refused.value.field == key


def test_an_aware_time_is_refused() -> None:
    from datetime import UTC

    with pytest.raises(ValidationFailed):
        policy_from_settings({"twiceADaySecondTime": time(14, 0, tzinfo=UTC)})


def test_wording_keys_are_accepted_and_are_not_policy() -> None:
    wording = dict(zip([r[0] for r in WORDING_ROWS], SAMPLE_VALUES, strict=True))
    assert policy_from_settings(wording) == DEFAULT_POLICY


def test_a_bad_wording_value_is_refused_by_policy_from_settings_too() -> None:
    with pytest.raises(ValidationFailed) as refused:
        policy_from_settings({"systemName": "a/b"})
    assert refused.value.field == "systemName"


def test_validate_value_checks_a_flag_exactly() -> None:
    spec = SettingSpec(
        key="exampleFlag",
        kind=SettingKind.BOOL,
        policy_field=None,
        unit="flag",
        default=False,
        minimum=None,
        maximum=None,
        choices=None,
        allowed=None,
        safety_class=SafetyClass.OPERATIONAL,
        scope=SettingScope.TENANT,
        required_for_activation=False,
    )
    assert validate_value(spec, True) is True
    assert validate_value(spec, False) is False
    for bad in (1, 0, "true", None):
        with pytest.raises(ValidationFailed) as refused:
            validate_value(spec, bad)
        assert refused.value.field == "exampleFlag"


def test_a_spec_is_read_only() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec_for("replyWindowMinutes").key = "x"  # type: ignore[misc]
    assert spec_for("replyWindowMinutes") == spec_for("replyWindowMinutes")


# ---------------------------------------------------------------- 12. cross-field rules

CROSS_CASES = (
    ({"replyWindowMinutes": 60, "reminderAfterMinutes": 30}, "reply"),
    ({"reminderAfterMinutes": 60, "phoneTaskAfterMinutes": 60}, "reminder"),
    ({"phoneTaskAfterMinutes": 90, "escalateAfterMinutes": 90}, "phone"),
    ({"pressureWatchFrom": 5, "pressureHighFrom": 5}, "pressure"),
    ({"bookingPhonePromptMinutes": 10, "bookingReplyWindowMinutes": 10}, "booking"),
)


@pytest.mark.parametrize(("overrides", "name"), CROSS_CASES, ids=[c[1] for c in CROSS_CASES])
def test_each_cross_field_rule_refuses_with_its_own_message(
    overrides: dict[str, Any], name: str
) -> None:
    with pytest.raises(ValidationFailed) as refused:
        policy_from_settings(overrides)
    assert refused.value.field in {"reminder_after", "phone_task_after", "escalate_after"} | {
        "pressure_high_from",
        "booking_phone_prompt_after",
    }, name


def test_the_five_cross_field_messages_differ() -> None:
    messages = set()
    for overrides, _name in CROSS_CASES:
        with pytest.raises(ValidationFailed) as refused:
            policy_from_settings(overrides)
        messages.add(refused.value.message)
    assert len(messages) == 5


def test_a_reply_window_equal_to_the_reminder_is_allowed_but_the_others_are_strict() -> None:
    assert policy_from_settings({"replyWindowMinutes": 30, "reminderAfterMinutes": 30})
    with pytest.raises(ValidationFailed):
        policy_from_settings({"reminderAfterMinutes": 60})  # phone task is 60: not strictly after


def test_the_defaults_and_the_tightest_ladder_pass() -> None:
    assert policy_from_settings({}) == DEFAULT_POLICY
    tight = policy_from_settings(
        {
            "replyWindowMinutes": 15,
            "reminderAfterMinutes": 15,
            "phoneTaskAfterMinutes": 30,
            "escalateAfterMinutes": 45,
        }
    )
    assert tight.escalate_after == timedelta(minutes=45)


def test_the_all_minimum_and_all_maximum_policies_are_legal() -> None:
    assert policy_from_settings(settings_at(4)).reply_window == timedelta(minutes=15)
    assert policy_from_settings(settings_at(5)).escalate_after == timedelta(minutes=360)


def test_the_policy_checks_a_value_that_does_not_come_through_the_registry() -> None:
    with pytest.raises(ValidationFailed):
        dataclasses.replace(DEFAULT_POLICY, reply_window=timedelta(minutes=20, seconds=1))
    with pytest.raises(ValidationFailed):
        dataclasses.replace(DEFAULT_POLICY, reply_window=30)
    with pytest.raises(ValidationFailed):
        dataclasses.replace(DEFAULT_POLICY, reply_window=30.0)
    with pytest.raises(ValidationFailed):
        dataclasses.replace(DEFAULT_POLICY, max_consecutive_confirms=True)
    with pytest.raises(ValidationFailed):
        dataclasses.replace(DEFAULT_POLICY, twice_a_day_second=time(14, 0, 1))
    with pytest.raises(ValidationFailed):
        dataclasses.replace(DEFAULT_POLICY, critical_alert_kinds={AlertKind.SERVICE_CLOSED})
    with pytest.raises(ValidationFailed):
        dataclasses.replace(DEFAULT_POLICY, critical_alert_kinds=frozenset({"service-closed"}))
    with pytest.raises(ValidationFailed):
        dataclasses.replace(DEFAULT_POLICY, alert_default_kinds=frozenset())
    with pytest.raises(ValidationFailed):
        dataclasses.replace(DEFAULT_POLICY, alert_default_not_updated_hours=3)


def test_a_policy_is_frozen_and_hashable() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        DEFAULT_POLICY.reply_window = timedelta(minutes=20)  # type: ignore[misc]
    assert hash(DEFAULT_POLICY) == hash(TenantPolicy())


# ---------------------------------------------------------------- 13. properties


def _value_strategy(row: tuple[Any, ...]) -> st.SearchStrategy[Any]:
    unit, minimum, maximum = row[2], row[4], row[5]
    if unit == "time-of-day":
        low, high = minimum.hour * 60, maximum.hour * 60
        return st.integers(low, high).map(lambda m: time(m // 60, m % 60))
    return st.integers(minimum, maximum)


def _outside_strategy(row: tuple[Any, ...]) -> st.SearchStrategy[Any]:
    unit, minimum, maximum = row[2], row[4], row[5]
    if unit == "time-of-day":
        low, high = minimum.hour * 60, maximum.hour * 60
        return (
            st.integers(0, 24 * 60 - 1)
            .filter(lambda m: m < low or m > high)
            .map(lambda m: time(m // 60, m % 60))
        )
    return st.one_of(st.integers(max_value=minimum - 1), st.integers(min_value=maximum + 1))


_OPTIONAL = {row[1]: _value_strategy(row) for row in GOLDEN}
_OPTIONAL["criticalAlertKinds"] = st.frozensets(st.sampled_from(ALL_KINDS), min_size=1)
_OPTIONAL["alertDefaultKinds"] = st.frozensets(st.sampled_from(ALL_KINDS), min_size=1)
_OPTIONAL["alertDefaultNotUpdatedHours"] = st.sampled_from([2, 4])
OVERRIDES = st.fixed_dictionaries({}, optional=_OPTIONAL)


def _merged(overrides: dict[str, Any]) -> dict[str, Any]:
    merged = {row[1]: row[3] for row in GOLDEN}
    merged.update(overrides)
    return merged


def _legal(m: dict[str, Any]) -> bool:
    return (
        m["replyWindowMinutes"] <= m["reminderAfterMinutes"]
        and m["reminderAfterMinutes"] < m["phoneTaskAfterMinutes"]
        and m["phoneTaskAfterMinutes"] < m["escalateAfterMinutes"]
        and m["pressureWatchFrom"] < m["pressureHighFrom"]
        and m["bookingPhonePromptMinutes"] < m["bookingReplyWindowMinutes"]
    )


@settings(max_examples=300, deadline=None)
@given(OVERRIDES)
def test_property_overrides_within_bounds_build_a_policy_and_round_trip(
    overrides: dict[str, Any],
) -> None:
    assume(_legal(_merged(overrides)))
    policy = policy_from_settings(overrides)
    assert policy_from_settings(policy.as_settings()) == policy
    assert policy_from_settings(policy_from_settings(overrides).as_settings()) == policy
    canonical = validate_settings(overrides)
    assert canonical == overrides
    for key, value in overrides.items():
        assert policy.as_settings()[key] == value


@settings(max_examples=300, deadline=None)
@given(st.data())
def test_property_a_value_outside_its_bounds_is_refused_with_validation_failed_only(
    data: st.DataObject,
) -> None:
    row = data.draw(st.sampled_from(GOLDEN))
    outside = data.draw(_outside_strategy(row))
    with pytest.raises(ValidationFailed):
        policy_from_settings({row[1]: outside})
    with pytest.raises(ValidationFailed):
        validate_value(spec_for(row[1]), outside)


@settings(max_examples=300, deadline=None)
@given(
    st.sampled_from([row[1] for row in GOLDEN] + [row[1] for row in SET_ROWS] + ["systemName"]),
    st.one_of(
        st.none(),
        st.booleans(),
        st.integers(),
        st.floats(),
        st.text(),
        st.binary(),
        st.times(),
        st.timedeltas(),
        st.frozensets(st.text()),
        st.lists(st.integers()),
    ),
)
def test_property_no_value_makes_the_registry_raise_anything_but_validation_failed(
    key: str, value: Any
) -> None:
    with contextlib.suppress(ValidationFailed):
        policy_from_settings({key: value})


def test_the_policy_as_settings_is_the_inverse_with_unit_values() -> None:
    values = DEFAULT_POLICY.as_settings()
    assert list(values) == [spec.key for spec in SETTING_SPECS[:24]]
    assert values["replyWindowMinutes"] == 30
    assert type(values["replyWindowMinutes"]) is int
    assert values["staleWarningHours"] == 2
    assert values["criteriaReminderDays"] == 14
    assert values["twiceADaySecondTime"] == time(14, 0)
    assert values["criticalAlertKinds"] == frozenset({"service-closed", "system-pressure"})
    assert all(type(kind) is str for kind in values["alertDefaultKinds"])  # type: ignore[union-attr]
    assert values["alertDefaultNotUpdatedHours"] == 2
    assert policy_from_settings(values) == DEFAULT_POLICY


# ---------------------------------------------------------------- 13a. require_policy


def test_require_policy_returns_the_same_object() -> None:
    assert require_policy(DEFAULT_POLICY) is DEFAULT_POLICY


class _PolicySubclass(TenantPolicy):
    pass


@pytest.mark.parametrize(
    "bad",
    [
        None,
        {},
        {"reply_window": 15},
        types.SimpleNamespace(**dataclasses.asdict(DEFAULT_POLICY)),
        DEFAULT_POLICY.as_settings(),
        "policy",
    ],
    ids=["none", "empty-dict", "dict", "namespace", "settings", "string"],
)
def test_require_policy_refuses_anything_that_is_not_a_tenant_policy(bad: Any) -> None:
    with pytest.raises(TypeError, match="a TenantPolicy is required"):
        require_policy(bad)


def test_require_policy_refuses_a_subclass_instance() -> None:
    # A subclass could carry another field or override a check; only the exact class passes.
    with pytest.raises(TypeError, match="a TenantPolicy is required"):
        require_policy(_PolicySubclass())


# ---------------------------------------------------------------- 14. approvals


def test_a_clinical_change_needs_two_approvers() -> None:
    assert approvals_required({}, {"replyWindowMinutes": 20}) == 2
    assert approvals_required({"replyWindowMinutes": 20}, {"replyWindowMinutes": 25}) == 2


def test_a_non_clinical_change_needs_one_approver() -> None:
    assert approvals_required({}, {"alertDefaultNotUpdatedHours": 4}) == 1
    assert approvals_required({}, {"systemName": "Example"}) == 1
    assert approvals_required({}, {}) == 1


def test_one_clinical_key_among_operational_ones_makes_the_change_clinical() -> None:
    new = {"alertDefaultNotUpdatedHours": 4, "staleWarningHours": 3}
    assert approvals_required({}, new) == 2


def test_setting_a_key_back_to_its_default_counts_as_a_change() -> None:
    assert changed_keys({"replyWindowMinutes": 20}, {}) == {"replyWindowMinutes"}
    assert changed_keys({}, {"replyWindowMinutes": 30}) == {"replyWindowMinutes"}
    assert approvals_required({"replyWindowMinutes": 20}, {}) == 2
    assert approvals_required({}, {"replyWindowMinutes": 30}) == 2


def test_changed_keys_lists_added_removed_and_altered_keys_only() -> None:
    old = {"replyWindowMinutes": 20, "staleWarningHours": 3, "systemName": "Example"}
    new = {"replyWindowMinutes": 25, "staleWarningHours": 3, "manyChangesCount": 4}
    assert changed_keys(old, new) == {"replyWindowMinutes", "systemName", "manyChangesCount"}
    assert changed_keys(new, new) == frozenset()
    assert changed_keys({}, {}) == frozenset()


def test_clinical_keys_filters_by_class_and_refuses_an_unknown_key() -> None:
    keys = {"replyWindowMinutes", "alertDefaultKinds", "systemName", "pressureHighFrom"}
    assert clinical_keys(keys) == {"replyWindowMinutes", "pressureHighFrom"}
    assert clinical_keys(frozenset()) == frozenset()
    with pytest.raises(ValidationFailed):
        clinical_keys({"notASetting"})
    with pytest.raises(ValidationFailed):
        approvals_required({}, {"notASetting": 1})


CLINICAL_NEW = {"replyWindowMinutes": 20}
OPERATIONAL_NEW = {"alertDefaultNotUpdatedHours": 4}


def test_two_approvers_who_are_not_the_author_pass_a_clinical_change() -> None:
    check_approvals({}, CLINICAL_NEW, "author-1", ["approver-1", "approver-2"])
    check_approvals({}, CLINICAL_NEW, "author-1", ("approver-1", "approver-2", "approver-3"))


@pytest.mark.parametrize(
    "approvers",
    [
        [],
        ["approver-1"],
        ["author-1", "approver-1"],
        ["approver-1", "author-1"],
        ["approver-1", "approver-1"],
        ["approver-1", ""],
        ["approver-1", "  "],
        ["approver-1", None],
        ["approver-1", 7],
        "approver-1approver-2",
        None,
        5,
        {"approver-1", "approver-2"},
    ],
    ids=[
        "none",
        "one",
        "author-first",
        "author-second",
        "equal",
        "empty",
        "blank",
        "none-ref",
        "number-ref",
        "a-bare-string",
        "no-list",
        "a-number",
        "a-set",
    ],
)
def test_a_clinical_change_is_refused_without_two_distinct_named_non_author_approvers(
    approvers: Any,
) -> None:
    with pytest.raises(NotAllowed):
        check_approvals({}, CLINICAL_NEW, "author-1", approvers)


def test_an_operational_change_needs_one_approver_who_may_be_the_author() -> None:
    check_approvals({}, OPERATIONAL_NEW, "author-1", ["approver-1"])
    check_approvals({}, OPERATIONAL_NEW, "author-1", ["author-1"])
    with pytest.raises(NotAllowed):
        check_approvals({}, OPERATIONAL_NEW, "author-1", [])
    with pytest.raises(NotAllowed):
        check_approvals({}, OPERATIONAL_NEW, "author-1", [""])
    with pytest.raises(NotAllowed):
        check_approvals({}, OPERATIONAL_NEW, "author-1", ["approver-1", "approver-1"])


def test_the_author_must_be_named() -> None:
    for author in ("", " ", None, 5):
        with pytest.raises(NotAllowed):
            check_approvals({}, CLINICAL_NEW, author, ["approver-1", "approver-2"])  # type: ignore[arg-type]


def test_a_clinical_restore_to_default_still_needs_two_approvers() -> None:
    with pytest.raises(NotAllowed):
        check_approvals({"replyWindowMinutes": 20}, {}, "author-1", ["approver-1"])
    check_approvals({"replyWindowMinutes": 20}, {}, "author-1", ["approver-1", "approver-2"])


def test_the_three_refusals_have_fixed_distinct_messages_that_name_no_ref() -> None:
    messages = set()
    for approvers in ([], ["author-1", "approver-1"], ["approver-1", "approver-1"]):
        with pytest.raises(NotAllowed) as refused:
            check_approvals({}, CLINICAL_NEW, "author-1", approvers)
        text = str(refused.value)
        assert "author-1" not in text and "approver-1" not in text
        messages.add(text)
    assert len(messages) == 3


# ---------------------------------------------------------------- 15. tenant text

TEXT_REFUSED = [
    "",
    " x",
    "x ",
    "a  b",
    "a/b",
    "a:b",
    "a@b",
    "a{b}",
    "a}b",
    "<b>",
    'a"b',
    "a\nb",
    "a\tb",
    "-abc",
    ".abc",
    "DT4 8XX",
    "1234567890",
    "943 476 5919",
    "Mrs Smith",
    "café",
    "a b",
]


@pytest.mark.parametrize("field", [row[1] for row in WORDING_ROWS])
@pytest.mark.parametrize("bad", TEXT_REFUSED)
def test_check_tenant_text_refuses(field: str, bad: str) -> None:
    with pytest.raises(ValidationFailed) as refused:
        check_tenant_text(field, bad)
    assert refused.value.field == field


@pytest.mark.parametrize("field", [row[1] for row in WORDING_ROWS])
def test_check_tenant_text_refuses_what_is_not_exactly_text(field: str) -> None:
    class Text(str):
        pass

    for bad in (None, 5, b"abc", Text("abc"), ["abc"]):
        with pytest.raises(ValidationFailed):
            check_tenant_text(field, bad)


@pytest.mark.parametrize(("key", "field", "limit"), WORDING_ROWS)
def test_check_tenant_text_has_a_length_limit_per_field(key: str, field: str, limit: int) -> None:
    assert check_tenant_text(field, "a" * limit) == "a" * limit
    with pytest.raises(ValidationFailed):
        check_tenant_text(field, "a" * (limit + 1))
    with pytest.raises(ValidationFailed):
        validate_value(spec_for(key), "a" * (limit + 1))
    assert validate_value(spec_for(key), "a" * limit) == "a" * limit


@pytest.mark.parametrize("value", [*SAMPLE_VALUES, "A", "Name (North), A&B+C-D 'x' 1.5"])
def test_check_tenant_text_returns_what_it_accepts_unchanged(value: str) -> None:
    for field in ("system_name", "referral_system_name", "coordination_team_name"):
        assert check_tenant_text(field, value) is value


def test_check_tenant_text_refuses_an_unknown_field() -> None:
    with pytest.raises(ValidationFailed) as refused:
        check_tenant_text("display_name", "Example")
    assert refused.value.field == "field"


# ---------------------------------------------------------------- 16. canary: no echo


def test_no_refusal_in_this_module_echoes_the_value_that_caused_it() -> None:
    probes: list[Any] = [
        lambda: policy_from_settings({CANARY: 1}),
        lambda: policy_from_settings({"systemName": CANARY + "/"}),
        lambda: policy_from_settings({"replyWindowMinutes": CANARY}),
        lambda: check_tenant_text("system_name", CANARY + "{"),
        lambda: check_tenant_text("system_name", CANARY + " Mrs Smith"),
        lambda: check_tenant_text(CANARY, "x"),
        lambda: check_approvals({}, CLINICAL_NEW, CANARY, [CANARY, "other"]),
        lambda: check_approvals({}, CLINICAL_NEW, "author", [CANARY, CANARY]),
        lambda: check_approvals({}, CLINICAL_NEW, "author", [CANARY]),
        lambda: clinical_keys({CANARY}),
        lambda: require_policy(CANARY),
    ]
    for probe in probes:
        with pytest.raises((ValidationFailed, NotAllowed, TypeError)) as refused:
            probe()
        assert "canary" not in str(refused.value)
