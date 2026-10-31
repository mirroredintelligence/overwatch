"""The tenant record, its identifier and time zone rules, contacts, wording and configuration
versions (TEN-006).

A tenant is the organisation that owns a service directory and its reporters: a legal entity and the
controller of its own data (DEC-132 item 1). The identifier is the value of the `tenantId`
property carried on every node (DEC-130 item 1). Pure: no I/O, no clock; the lifecycle moves are in
`rules/tenant_lifecycle.py`, the settings in `rules/tenant_settings.py`.

Fail closed: an enum member is checked by its exact type (lessons L3 and L38: `"active"` and
`NumberStatus.ACTIVE` both equal `TenantStatus.ACTIVE`), a datetime must be timezone-aware, and the
status and its timestamps must agree. No refusal carries a value, so no tenant id, name, reference,
number or address ever reaches an error message. The tenant-specific words of a message are the
`TenantWording` fields only; nothing here names a place or a deployment.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from itertools import pairwise
from types import MappingProxyType
from typing import Final, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from diucs.domain.errors import ValidationFailed
from diucs.domain.messages.privacy_guard import find_patient_data
from diucs.domain.model.tenant_policy import SettingValue, TenantPolicy
from diucs.domain.rules.tenant_settings import (
    check_tenant_text,
    policy_from_settings,
    validate_settings,
)

# ---------------------------------------------------------------- identifiers

# 2 to 31 characters of lower case letters, digits and hyphen, starting with a letter or digit.
# Always used with `fullmatch`. This is a second copy of TEN-001's `TENANT_ID_PATTERN` (the domain
# may not import the application layer, DEC-011): a parity test keeps the two equal.
TENANT_ID_PATTERN: Final = re.compile(r"[a-z0-9][a-z0-9-]{1,30}")
# The scope value of platform-level nodes (audit F section 2.3).
RESERVED_TENANT_IDS: Final = frozenset({"platform"})
# Network scope ids start with this prefix, so a tenant id may not.
RESERVED_TENANT_PREFIX: Final = "net-"

TENANT_ID_MESSAGE: Final = "is not a valid tenant id"
WRONG_TYPE_MESSAGE: Final = "has the wrong type"
NAIVE_MESSAGE: Final = "must be a timezone-aware datetime"
MISMATCH_MESSAGE: Final = "does not match the status"

# DEC-136 item 13: one zone for now, the allow-list grows by decision.
DEFAULT_TIME_ZONE: Final = "Europe/London"
ALLOWED_TIME_ZONES: Final = frozenset({DEFAULT_TIME_ZONE})
TIME_ZONE_MESSAGE: Final = "is not an allowed time zone"

NAME_MAX_LENGTH: Final = 120
COUNTRY_PATTERN: Final = re.compile(r"[A-Z]{2}")
ODS_PATTERN: Final = re.compile(r"[A-Z0-9]{3,8}")
# A reference is an id for a document, never the document and never free text (audit F 2.3).
REFERENCE_PATTERN: Final = re.compile(r"[A-Za-z0-9 ._:/-]+")
REFERENCE_MAX_LENGTH: Final = 80
HASH_KEY_VERSIONS: Final = frozenset({0, 1})


def check_tenant_id(value: object) -> str:
    """The value, when it is exactly a `str` that fullmatches the id pattern, is not reserved and
    does not start with the network prefix. The refusal names no value."""
    if (
        type(value) is not str
        or TENANT_ID_PATTERN.fullmatch(value) is None
        or value in RESERVED_TENANT_IDS
        or value.startswith(RESERVED_TENANT_PREFIX)
    ):
        raise ValidationFailed("tenant_id", TENANT_ID_MESSAGE)
    return value


def check_time_zone(value: object) -> str:
    """The value, when it is on the allow-list (an allow-list, not "any name zoneinfo can load")
    and the zone database can load it."""
    if type(value) is not str or value not in ALLOWED_TIME_ZONES:
        raise ValidationFailed("time_zone", TIME_ZONE_MESSAGE)
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError, ValueError, OSError:
        raise ValidationFailed("time_zone", TIME_ZONE_MESSAGE) from None
    return value


# ---------------------------------------------------------------- enums


class OrganisationType(StrEnum):
    NHS_TRUST = "nhs-trust"
    ICB = "icb"
    GP_PRACTICE = "gp-practice"
    LOCAL_AUTHORITY = "local-authority"
    VOLUNTARY_INDEPENDENT = "voluntary-independent"
    OTHER = "other"


class TenantStatus(StrEnum):
    PROVISIONING = "provisioning"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    OFFBOARDING = "offboarding"
    OFFBOARDED = "offboarded"
    PURGED = "purged"


class SuspendMode(StrEnum):
    READ_ONLY = "read-only"
    BLOCKED = "blocked"


class SuspendReason(StrEnum):
    """A fixed list, never free text. [ASSUMED] (DEC-155)."""

    SECURITY_INCIDENT = "security-incident"
    INFORMATION_GOVERNANCE = "information-governance"
    CLINICAL_SAFETY = "clinical-safety"
    CONTRACT = "contract"
    OPERATOR_REQUEST = "operator-request"


class RetentionClass(StrEnum):
    CAPACITY_REPORTS = "capacity-reports"
    BOOKINGS = "bookings"
    CASE_AUDIT = "case-audit"
    COMMUNICATIONS = "communications"
    TELEMETRY_RAW = "telemetry-raw"
    TELEMETRY_AGGREGATES = "telemetry-aggregates"
    AUDIT_CHAIN = "audit-chain"
    SAFETY_CONCERNS = "safety-concerns"


REQUIRED_RETENTION_CLASSES: Final = frozenset(RetentionClass)


class ContactKind(StrEnum):
    COORDINATION_PHONE = "coordination-phone"
    SUPPORT_EMAIL = "support-email"
    SHIFT_LEAD_ESCALATION = "shift-lead-escalation"
    CLINICAL_SAFETY_OFFICER = "clinical-safety-officer"
    ADVISOR_LINE = "advisor-line"
    """The number a clinician phones when an advisor has no work phone of their own: a desk or
    switchboard, never a person (W9G)."""


class ConfigStatus(StrEnum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending-approval"
    CURRENT = "current"
    SUPERSEDED = "superseded"


class NumberStatus(StrEnum):
    ACTIVE = "active"
    RETIRED = "retired"
    QUARANTINED = "quarantined"


# ---------------------------------------------------------------- field checks


def _enum(name: str, value: object, enum_type: type[StrEnum]) -> None:
    if type(value) is not enum_type:
        raise ValidationFailed(name, WRONG_TYPE_MESSAGE)


def _aware(name: str, value: object) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValidationFailed(name, NAIVE_MESSAGE)


def _optional_aware(name: str, value: object) -> None:
    if value is not None:
        _aware(name, value)


def _whole_number(name: str, value: object, minimum: int) -> None:
    if type(value) is not int or value < minimum:
        raise ValidationFailed(name, "must be a whole number that is not too small")


def _name(name: str, value: object) -> None:
    if (
        type(value) is not str
        or not 1 <= len(value) <= NAME_MAX_LENGTH
        or not value.isprintable()
        or find_patient_data(value)
    ):
        raise ValidationFailed(name, "must be 1 to 120 characters of plain text")


def _reference(name: str, value: object) -> None:
    if (
        type(value) is not str
        or len(value) > REFERENCE_MAX_LENGTH
        or REFERENCE_PATTERN.fullmatch(value) is None
        or value != value.strip()
    ):
        raise ValidationFailed(name, "must be a short reference id")


def _optional_reference(name: str, value: object) -> None:
    if value is not None:
        _reference(name, value)


_OFFBOARDING_STARTED: Final = frozenset(
    {TenantStatus.OFFBOARDING, TenantStatus.OFFBOARDED, TenantStatus.PURGED}
)
_OFFBOARDED: Final = frozenset({TenantStatus.OFFBOARDED, TenantStatus.PURGED})
_PURGED: Final = frozenset({TenantStatus.PURGED})
_SUSPENDED: Final = frozenset({TenantStatus.SUSPENDED})


@dataclass(frozen=True, slots=True, kw_only=True)
class Tenant:
    """A tenant. Keyword-only, because the fields keep the order of the prompt and two of them
    that come before `status` have defaults. `dataclasses.replace` runs every check again."""

    id: str
    display_name: str
    legal_name: str
    organisation_type: OrganisationType
    country_code: str = "GB"
    time_zone: str = DEFAULT_TIME_ZONE
    status: TenantStatus
    created_at: datetime
    activated_at: datetime | None = None
    suspended_at: datetime | None = None
    offboarding_started_at: datetime | None = None
    offboarded_at: datetime | None = None
    purged_at: datetime | None = None
    suspend_mode: SuspendMode | None = None
    suspend_reason: SuspendReason | None = None
    retention_hold_until: datetime | None = None
    ods_code: str | None = None
    epoch: int = 1
    hash_key_version: int = 1
    current_config_version: int | None = None
    dsa_ref: str | None = None
    dpia_ref: str | None = None
    dcb0160_ref: str | None = None

    def __post_init__(self) -> None:
        check_tenant_id(self.id)
        _name("display_name", self.display_name)
        _name("legal_name", self.legal_name)
        _enum("organisation_type", self.organisation_type, OrganisationType)
        if (
            type(self.country_code) is not str
            or COUNTRY_PATTERN.fullmatch(self.country_code) is None
        ):
            raise ValidationFailed("country_code", "must be two upper case letters")
        check_time_zone(self.time_zone)
        _enum("status", self.status, TenantStatus)
        _aware("created_at", self.created_at)
        for name in (
            "activated_at",
            "suspended_at",
            "offboarding_started_at",
            "offboarded_at",
            "purged_at",
            "retention_hold_until",
        ):
            _optional_aware(name, getattr(self, name))
        if self.suspend_mode is not None:
            _enum("suspend_mode", self.suspend_mode, SuspendMode)
        if self.suspend_reason is not None:
            _enum("suspend_reason", self.suspend_reason, SuspendReason)
        _whole_number("epoch", self.epoch, 1)
        if type(self.hash_key_version) is not int or self.hash_key_version not in HASH_KEY_VERSIONS:
            raise ValidationFailed("hash_key_version", "must be 0 or 1")
        if self.current_config_version is not None:
            _whole_number("current_config_version", self.current_config_version, 1)
        if self.ods_code is not None and (
            type(self.ods_code) is not str or ODS_PATTERN.fullmatch(self.ods_code) is None
        ):
            raise ValidationFailed("ods_code", "must be 3 to 8 upper case letters or digits")
        _optional_reference("dsa_ref", self.dsa_ref)
        _optional_reference("dpia_ref", self.dpia_ref)
        _optional_reference("dcb0160_ref", self.dcb0160_ref)
        self._check_status_and_times()

    def _check_status_and_times(self) -> None:
        """The status and its timestamps agree, and the set timestamps are in order."""
        status = self.status
        if status is not TenantStatus.PROVISIONING and self.activated_at is None:
            raise ValidationFailed("activated_at", MISMATCH_MESSAGE)
        for name, value, statuses in (
            ("offboarding_started_at", self.offboarding_started_at, _OFFBOARDING_STARTED),
            ("offboarded_at", self.offboarded_at, _OFFBOARDED),
            ("purged_at", self.purged_at, _PURGED),
            ("suspended_at", self.suspended_at, _SUSPENDED),
            ("suspend_mode", self.suspend_mode, _SUSPENDED),
            ("suspend_reason", self.suspend_reason, _SUSPENDED),
        ):
            if (value is not None) != (status in statuses):
                raise ValidationFailed(name, MISMATCH_MESSAGE)
        chain = [
            moment
            for moment in (
                self.created_at,
                self.activated_at,
                self.offboarding_started_at,
                self.offboarded_at,
                self.purged_at,
            )
            if moment is not None
        ]
        if any(earlier > later for earlier, later in pairwise(chain)):
            raise ValidationFailed("created_at", "the timestamps are out of order")
        # A suspension can fall anywhere after activation (it never coexists with the later ones).
        if (
            self.suspended_at is not None
            and self.activated_at is not None
            and self.suspended_at < self.activated_at
        ):
            raise ValidationFailed("suspended_at", "the timestamps are out of order")


# ---------------------------------------------------------------- contacts and wording

CONTACT_LABEL_MAX_LENGTH: Final = 60
CONTACT_VALUE_MAX_LENGTH: Final = 254
# A telephone number: a role or switchboard number, never a person.
PHONE_PATTERN: Final = re.compile(r"\+?[0-9][0-9 ]{5,18}[0-9]")
EMAIL_PATTERN: Final = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
# Nothing that could be a placeholder, markup or a control character may enter a text message.
CONTACT_FORBIDDEN_CHARACTERS: Final = frozenset("{}<>")
_PHONE_KINDS: Final = frozenset(
    {ContactKind.COORDINATION_PHONE, ContactKind.SHIFT_LEAD_ESCALATION, ContactKind.ADVISOR_LINE}
)


def _contact_text(name: str, value: object, maximum: int) -> str:
    if (
        type(value) is not str
        or not 1 <= len(value) <= maximum
        or not value.isprintable()
        or any(character in CONTACT_FORBIDDEN_CHARACTERS for character in value)
        or find_patient_data(value)
    ):
        raise ValidationFailed(name, "must be plain text of the right length")
    return value


@dataclass(frozen=True, slots=True)
class TenantContact:
    """An organisational contact: a role phone or a team address, never a person."""

    kind: ContactKind
    label: str
    value: str

    def __post_init__(self) -> None:
        _enum("kind", self.kind, ContactKind)
        _contact_text("label", self.label, CONTACT_LABEL_MAX_LENGTH)
        _contact_text("value", self.value, CONTACT_VALUE_MAX_LENGTH)
        pattern = PHONE_PATTERN if self.kind in _PHONE_KINDS else EMAIL_PATTERN
        if pattern.fullmatch(self.value) is None:
            raise ValidationFailed("value", "is not the right shape for this kind of contact")


@dataclass(frozen=True, slots=True)
class TenantWording:
    """The only tenant-specific words a message template may print. No defaults (H-T15): a tenant
    that has not set them cannot be activated."""

    system_name: str
    referral_system_name: str
    coordination_team_name: str

    def __post_init__(self) -> None:
        check_tenant_text("system_name", self.system_name)
        check_tenant_text("referral_system_name", self.referral_system_name)
        check_tenant_text("coordination_team_name", self.coordination_team_name)


# ---------------------------------------------------------------- configuration versions

CONFIG_REASON_MAX_LENGTH: Final = 40
CONFIG_REASON_PATTERN: Final = re.compile(r"[A-Za-z0-9-]*")
WORDING_KEYS: Final = ("systemName", "referralSystemName", "coordinationTeamName")


@dataclass(frozen=True, slots=True)
class TenantConfig:
    """One version of a tenant's configuration: only the overrides of the defaults, validated and
    stored read-only. A `current` or `superseded` version is frozen by construction; the legal
    moves between statuses are `transition_config` in `rules/tenant_lifecycle.py`."""

    version: int
    status: ConfigStatus
    values: Mapping[str, SettingValue]
    created_at: datetime
    created_by_ref: str
    effective_from: datetime | None = None
    approved_by_refs: tuple[str, ...] = ()
    reason_code: str = ""

    def __post_init__(self) -> None:
        _whole_number("version", self.version, 1)
        _enum("status", self.status, ConfigStatus)
        if not isinstance(self.values, Mapping):
            raise ValidationFailed("values", "must be a mapping")
        # A copy, so the caller's dict can change nothing, and read-only so nobody else can.
        object.__setattr__(self, "values", MappingProxyType(validate_settings(self.values)))
        _aware("created_at", self.created_at)
        _reference("created_by_ref", self.created_by_ref)
        _optional_aware("effective_from", self.effective_from)
        if self.status is ConfigStatus.CURRENT and self.effective_from is None:
            raise ValidationFailed("effective_from", "is required for a current version")
        if type(self.approved_by_refs) is not tuple:
            raise ValidationFailed("approved_by_refs", WRONG_TYPE_MESSAGE)
        for ref in self.approved_by_refs:
            _reference("approved_by_refs", ref)
        if len(set(self.approved_by_refs)) != len(self.approved_by_refs):
            raise ValidationFailed("approved_by_refs", "must be different people")
        if (
            type(self.reason_code) is not str
            or len(self.reason_code) > CONFIG_REASON_MAX_LENGTH
            or CONFIG_REASON_PATTERN.fullmatch(self.reason_code) is None
        ):
            raise ValidationFailed("reason_code", "must be letters, digits and hyphens")

    @property
    def policy(self) -> TenantPolicy:
        """The policy these overrides make (the defaults for any key not overridden)."""
        return policy_from_settings(self.values)

    @property
    def wording(self) -> TenantWording | None:
        """The wording, or None unless all three wording keys are set."""
        if not all(key in self.values for key in WORDING_KEYS):
            return None
        return TenantWording(
            system_name=cast(str, self.values["systemName"]),
            referral_system_name=cast(str, self.values["referralSystemName"]),
            coordination_team_name=cast(str, self.values["coordinationTeamName"]),
        )
