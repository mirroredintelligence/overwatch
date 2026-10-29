"""STUB for the red commit (DEC-010): names and shapes only, no checks. TEN-006 replaces it."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from diucs.domain.model.tenant_policy import SettingValue, TenantPolicy

TENANT_ID_PATTERN: Final = re.compile(r"[a-z0-9][a-z0-9-]{1,30}")
RESERVED_TENANT_IDS: Final = frozenset({"platform"})
RESERVED_TENANT_PREFIX: Final = "net-"
DEFAULT_TIME_ZONE: Final = "Europe/London"
ALLOWED_TIME_ZONES: Final = frozenset({DEFAULT_TIME_ZONE})


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


class ConfigStatus(StrEnum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending-approval"
    CURRENT = "current"
    SUPERSEDED = "superseded"


class NumberStatus(StrEnum):
    ACTIVE = "active"
    RETIRED = "retired"
    QUARANTINED = "quarantined"


def check_tenant_id(value: object) -> str:
    return value  # type: ignore[return-value]


def check_time_zone(value: object) -> str:
    return value  # type: ignore[return-value]


@dataclass(frozen=True, slots=True, kw_only=True)
class Tenant:
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


@dataclass(frozen=True, slots=True)
class TenantContact:
    kind: ContactKind
    label: str
    value: str


@dataclass(frozen=True, slots=True)
class TenantWording:
    system_name: str
    referral_system_name: str
    coordination_team_name: str


@dataclass(frozen=True, slots=True)
class TenantConfig:
    version: int
    status: ConfigStatus
    values: Mapping[str, SettingValue]
    created_at: datetime
    created_by_ref: str
    effective_from: datetime | None = None
    approved_by_refs: tuple[str, ...] = ()
    reason_code: str = ""

    @property
    def policy(self) -> TenantPolicy:
        return TenantPolicy()

    @property
    def wording(self) -> TenantWording | None:
        return None
