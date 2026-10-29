"""STUB for the red commit (DEC-010): names and signatures only, no checks. TEN-006 replaces it."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import time
from enum import StrEnum

from diucs.domain.model.tenant_policy import DEFAULT_POLICY, SettingValue, TenantPolicy


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


SETTING_SPECS: tuple[SettingSpec, ...] = ()


def spec_for(key: str) -> SettingSpec:
    raise NotImplementedError


def validate_value(spec: SettingSpec, value: object) -> SettingValue:
    return value  # type: ignore[return-value]


def policy_from_settings(values: Mapping[str, SettingValue]) -> TenantPolicy:
    return DEFAULT_POLICY


def validate_settings(values: Mapping[str, SettingValue]) -> dict[str, SettingValue]:
    return dict(values)


def changed_keys(
    old: Mapping[str, SettingValue], new: Mapping[str, SettingValue]
) -> frozenset[str]:
    return frozenset()


def clinical_keys(keys: frozenset[str] | set[str]) -> frozenset[str]:
    return frozenset()


def approvals_required(old: Mapping[str, SettingValue], new: Mapping[str, SettingValue]) -> int:
    return 1


def check_approvals(
    old: Mapping[str, SettingValue],
    new: Mapping[str, SettingValue],
    author_ref: str,
    approver_refs: Sequence[str],
) -> None:
    return None


def check_tenant_text(field: str, value: object) -> str:
    return value  # type: ignore[return-value]
