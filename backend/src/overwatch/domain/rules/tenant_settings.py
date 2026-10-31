"""The tenant setting registry, validation, approvals and the wording text rule (TEN-006).

A setting is one named, bounded, classified value a tenant may override. The registry
(`SETTING_SPECS`) holds the 24 policy settings of `TenantPolicy` and the three wording settings.
Defaults and bounds of the policy rows are read from `DEFAULT_POLICY` and `FIELD_BOUNDS`: one
source, no number retyped here. Later tasks add rows to this tuple (TEN-026, TEN-064, TEN-065,
TEN-066, TEN-036); each has a dependency path to this task, so no two edit it at once.

Fail closed (DEC-155): an unknown key, a value of the wrong exact type, a value outside its bounds
or an unlisted choice, and a contradictory set of thresholds are all `ValidationFailed`. A clinical
setting changes only with two approvers who are not its author (the DEC-032 pattern); the
approver check lives here as a pure function and the use case supplies the people.

No error carries a value, a tenant, a name or a reference. Standard library and `diucs.domain` only.
"""

import dataclasses
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import time
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final, cast

from diucs.domain.errors import NotAllowed, ValidationFailed
from diucs.domain.messages.privacy_guard import find_patient_data
from diucs.domain.model.tenant_policy import (
    ALERT_KIND_VALUES,
    ALERT_NOT_UPDATED_CHOICES,
    DEFAULT_POLICY,
    FIELD_BOUNDS,
    NOT_ALLOWED_VALUE_MESSAGE,
    OUTSIDE_RANGE_MESSAGE,
    POLICY_FIELD_BY_KEY,
    POLICY_FIELDS,
    WRONG_TYPE_MESSAGE,
    PolicyField,
    SettingValue,
    Shape,
    TenantPolicy,
    from_setting_value,
    to_setting_value,
)

__all__ = [
    "SETTING_SPECS",
    "SafetyClass",
    "SettingKind",
    "SettingScope",
    "SettingSpec",
    "SettingValue",
    "approvals_required",
    "changed_keys",
    "check_approvals",
    "check_tenant_text",
    "clinical_keys",
    "is_named_ref",
    "policy_from_settings",
    "spec_for",
    "validate_settings",
    "validate_value",
]

# A clinical change needs two approvers who are not the author; any other change needs one.
CLINICAL_APPROVALS_REQUIRED: Final = 2
ORDINARY_APPROVALS_REQUIRED: Final = 1

# Wording (rule 10): the only tenant-specific words a message template may print.
TEXT_PATTERN: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9 .,'&()+-]*")
TEXT_MIN_LENGTH: Final = 1
SYSTEM_NAME_MAX: Final = 60  # [ASSUMED]
REFERRAL_SYSTEM_NAME_MAX: Final = 40  # [ASSUMED]
COORDINATION_TEAM_NAME_MAX: Final = 60  # [ASSUMED]
TEXT_LIMITS: Final = MappingProxyType(
    {
        "system_name": SYSTEM_NAME_MAX,
        "referral_system_name": REFERRAL_SYSTEM_NAME_MAX,
        "coordination_team_name": COORDINATION_TEAM_NAME_MAX,
    }
)

UNIT_TEXT: Final = "text"

KEY_REFUSED_MESSAGE: Final = "not a tenant setting"
TEXT_MESSAGE: Final = "must be plain text of the right length"
VALUES_MESSAGE: Final = "must be a mapping"
AUTHOR_UNNAMED_MESSAGE: Final = "the author of the change must be named"
APPROVERS_MESSAGE: Final = "the approvers must be named and different"
APPROVER_COUNT_MESSAGE: Final = "the change has too few approvers"
AUTHOR_APPROVES_MESSAGE: Final = "the author cannot approve a clinical change"


class SettingKind(StrEnum):
    INT = "int"
    TEXT = "text"
    BOOL = "bool"
    TIME = "time"
    CODES = "codes"


class SafetyClass(StrEnum):
    CLINICAL = "clinical"
    OPERATIONAL = "operational"


class SettingScope(StrEnum):
    TENANT = "tenant"
    NETWORK = "network"
    BOTH = "both"


@dataclass(frozen=True, slots=True)
class SettingSpec:
    """One registry row. `minimum` and `maximum` are in the unit of the key (for text: the
    shortest and longest length), `choices` and `allowed` list the only values a row accepts."""

    key: str
    kind: SettingKind
    policy_field: str | None
    unit: str
    default: SettingValue | None
    minimum: int | time | None
    maximum: int | time | None
    choices: frozenset[int] | None
    allowed: frozenset[str] | None
    safety_class: SafetyClass
    scope: SettingScope
    required_for_activation: bool


# ---------------------------------------------------------------- the registry

# Anything not listed here is a clinical setting on tenant scope: a new row is the safe kind
# until a decision says otherwise.
_OPERATIONAL_KEYS: Final = frozenset({"alertDefaultKinds", "alertDefaultNotUpdatedHours"})
_NETWORK_KEYS: Final = frozenset({"pressureWatchFrom", "pressureHighFrom"})


def _policy_spec(field: PolicyField) -> SettingSpec:
    bounds = FIELD_BOUNDS.get(field.name)
    minimum = None if bounds is None else to_setting_value(field, bounds[0])
    maximum = None if bounds is None else to_setting_value(field, bounds[1])
    return SettingSpec(
        key=field.key,
        kind={
            Shape.TIME_OF_DAY: SettingKind.TIME,
            Shape.CODES: SettingKind.CODES,
        }.get(field.shape, SettingKind.INT),
        policy_field=field.name,
        unit=field.unit,
        default=DEFAULT_POLICY.as_settings()[field.key],
        minimum=cast(int | time | None, minimum),
        maximum=cast(int | time | None, maximum),
        choices=ALERT_NOT_UPDATED_CHOICES if field.shape is Shape.CHOICE else None,
        allowed=ALERT_KIND_VALUES if field.shape is Shape.CODES else None,
        safety_class=(
            SafetyClass.OPERATIONAL if field.key in _OPERATIONAL_KEYS else SafetyClass.CLINICAL
        ),
        scope=SettingScope.BOTH if field.key in _NETWORK_KEYS else SettingScope.TENANT,
        required_for_activation=False,
    )


def _wording_spec(key: str, field_name: str) -> SettingSpec:
    return SettingSpec(
        key=key,
        kind=SettingKind.TEXT,
        policy_field=None,
        unit=UNIT_TEXT,
        default=None,
        minimum=TEXT_MIN_LENGTH,
        maximum=TEXT_LIMITS[field_name],
        choices=None,
        allowed=None,
        safety_class=SafetyClass.OPERATIONAL,
        scope=SettingScope.TENANT,
        required_for_activation=True,
    )


SETTING_SPECS: Final[tuple[SettingSpec, ...]] = (
    *(_policy_spec(field) for field in POLICY_FIELDS),
    _wording_spec("systemName", "system_name"),
    _wording_spec("referralSystemName", "referral_system_name"),
    _wording_spec("coordinationTeamName", "coordination_team_name"),
)
_SPEC_BY_KEY: Final = MappingProxyType({spec.key: spec for spec in SETTING_SPECS})


def spec_for(key: str) -> SettingSpec:
    """The registry row of a key. An unknown key is refused, never ignored (fail closed)."""
    spec = _SPEC_BY_KEY.get(key)
    if spec is None:
        raise ValidationFailed("key", KEY_REFUSED_MESSAGE)
    return spec


# ---------------------------------------------------------------- wording text


def _check_text(name: str, value: object, maximum: int) -> str:
    if type(value) is not str or not TEXT_MIN_LENGTH <= len(value) <= maximum:
        raise ValidationFailed(name, TEXT_MESSAGE)
    if value.endswith(" ") or "  " in value or TEXT_PATTERN.fullmatch(value) is None:
        raise ValidationFailed(name, TEXT_MESSAGE)
    if find_patient_data(value):
        raise ValidationFailed(name, TEXT_MESSAGE)
    return value


def check_tenant_text(field: str, value: object) -> str:
    """The wording a tenant may print in a message: plain letters, digits and a few marks, no
    link, address or markup, no patient-data shape. Returns the value unchanged."""
    maximum = TEXT_LIMITS.get(field)
    if maximum is None:
        raise ValidationFailed("field", "not a wording field")
    return _check_text(field, value, maximum)


# ---------------------------------------------------------------- validation


def _check_int(spec: SettingSpec, value: object) -> int:
    if type(value) is not int:
        raise ValidationFailed(spec.key, WRONG_TYPE_MESSAGE)
    if spec.choices is not None:
        if value not in spec.choices:
            raise ValidationFailed(spec.key, NOT_ALLOWED_VALUE_MESSAGE)
    elif not cast(int, spec.minimum) <= value <= cast(int, spec.maximum):
        raise ValidationFailed(spec.key, OUTSIDE_RANGE_MESSAGE)
    return value


def _check_time(spec: SettingSpec, value: object) -> time:
    if type(value) is not time or value.tzinfo is not None:
        raise ValidationFailed(spec.key, WRONG_TYPE_MESSAGE)
    if value.second or value.microsecond:
        raise ValidationFailed(spec.key, WRONG_TYPE_MESSAGE)
    if not cast(time, spec.minimum) <= value <= cast(time, spec.maximum):
        raise ValidationFailed(spec.key, OUTSIDE_RANGE_MESSAGE)
    return value


def _check_codes(spec: SettingSpec, value: object) -> frozenset[str]:
    if type(value) is not frozenset:
        raise ValidationFailed(spec.key, WRONG_TYPE_MESSAGE)
    allowed = spec.allowed or frozenset()
    if not value or any(type(code) is not str or code not in allowed for code in value):
        raise ValidationFailed(spec.key, NOT_ALLOWED_VALUE_MESSAGE)
    return value


def validate_value(spec: SettingSpec, value: object) -> SettingValue:
    """The value, when it has the exact type of its row and lies within its bounds or choices."""
    if spec.kind is SettingKind.INT:
        return _check_int(spec, value)
    if spec.kind is SettingKind.TIME:
        return _check_time(spec, value)
    if spec.kind is SettingKind.CODES:
        return _check_codes(spec, value)
    if spec.kind is SettingKind.TEXT:
        return _check_text(spec.key, value, cast(int, spec.maximum))
    if type(value) is not bool:
        raise ValidationFailed(spec.key, WRONG_TYPE_MESSAGE)
    return value


def policy_from_settings(values: Mapping[str, SettingValue]) -> TenantPolicy:
    """The policy these overrides make: a key that is absent takes its default, every key present
    is validated, an unknown key is refused, wording keys are checked and are not policy."""
    if not isinstance(values, Mapping):
        raise ValidationFailed("values", VALUES_MESSAGE)
    overrides: dict[str, Any] = {}
    for key, value in values.items():
        spec = spec_for(key)
        checked = validate_value(spec, value)
        if spec.policy_field is not None:
            overrides[spec.policy_field] = from_setting_value(POLICY_FIELD_BY_KEY[key], checked)
    # Built through the policy so its cross-field rules run.
    return dataclasses.replace(DEFAULT_POLICY, **overrides)


def validate_settings(values: Mapping[str, SettingValue]) -> dict[str, SettingValue]:
    """The canonical override mapping: every value checked, in registry order. The policy is built
    for its cross-field rules; wording goes through the same check as `check_tenant_text`."""
    policy_from_settings(values)
    return {
        spec.key: validate_value(spec, values[spec.key])
        for spec in SETTING_SPECS
        if spec.key in values
    }


# ---------------------------------------------------------------- approvals

_ABSENT: Final = object()


def changed_keys(
    old: Mapping[str, SettingValue], new: Mapping[str, SettingValue]
) -> frozenset[str]:
    """Keys that were added, removed or given another value. Setting a key back to its default is
    a change like any other: the default is a value too."""
    return frozenset(key for key in {*old, *new} if old.get(key, _ABSENT) != new.get(key, _ABSENT))


def clinical_keys(keys: frozenset[str] | set[str]) -> frozenset[str]:
    """The keys of the clinical class. An unknown key is refused."""
    return frozenset(key for key in keys if spec_for(key).safety_class is SafetyClass.CLINICAL)


def approvals_required(old: Mapping[str, SettingValue], new: Mapping[str, SettingValue]) -> int:
    """Two for a change that touches a clinical key, otherwise one."""
    if clinical_keys(changed_keys(old, new)):
        return CLINICAL_APPROVALS_REQUIRED
    return ORDINARY_APPROVALS_REQUIRED


def is_named_ref(ref: object) -> bool:
    """True for a reference that is exactly text and not blank (an actor, an operator, a person)."""
    return type(ref) is str and bool(ref.strip())


def check_approvals(
    old: Mapping[str, SettingValue],
    new: Mapping[str, SettingValue],
    author_ref: str,
    approver_refs: Sequence[str],
) -> None:
    """Refuse (`NotAllowed`) unless the change has enough approvers, all named and different, and
    for a clinical change none of them is its author (the DEC-032 pattern). No ref is echoed."""
    required = approvals_required(old, new)
    if not is_named_ref(author_ref):
        raise NotAllowed(AUTHOR_UNNAMED_MESSAGE)
    if (
        isinstance(approver_refs, str)
        or not isinstance(approver_refs, Sequence)
        or len(approver_refs) < required
    ):
        raise NotAllowed(APPROVER_COUNT_MESSAGE)
    if not all(is_named_ref(ref) for ref in approver_refs) or len(set(approver_refs)) != len(
        approver_refs
    ):
        raise NotAllowed(APPROVERS_MESSAGE)
    if required == CLINICAL_APPROVALS_REQUIRED and author_ref in approver_refs:
        raise NotAllowed(AUTHOR_APPROVES_MESSAGE)
