"""STUB for the red commit (DEC-010): names and signatures only, no checks. TEN-006 replaces it."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from diucs.domain.model.tenant import (
    ConfigStatus,
    ContactKind,
    NumberStatus,
    RetentionClass,
    SuspendMode,
    SuspendReason,
    Tenant,
    TenantStatus,
)

OFFBOARDING_NOTICE: Final = timedelta(days=30)
NUMBER_QUARANTINE: Final = timedelta(days=90)
PURGE_OPERATORS_REQUIRED: Final = 2


@dataclass(frozen=True, slots=True)
class ActivationFacts:
    config_approved: bool
    time_zone: str | None
    active_numbers_tested: int
    email_in_use: bool
    email_sender_verified: bool
    first_admin_invited: bool
    entra_binding_verified: bool
    role_mappings: int
    contact_kinds: frozenset[ContactKind]
    retention_classes_set: frozenset[RetentionClass]
    references_recorded: frozenset[str]
    wording_complete: bool
    registers_services: bool
    area_districts_set: bool
    network_member: bool
    agreement_accepted: bool


def transition_tenant(current: TenantStatus, target: TenantStatus) -> TenantStatus:
    return target


def transition_config(current: ConfigStatus, target: ConfigStatus) -> ConfigStatus:
    return target


def suspend_tenant(
    tenant: Tenant, mode: SuspendMode, reason: SuspendReason, now: datetime
) -> Tenant:
    return tenant


def resume_tenant(tenant: Tenant, now: datetime) -> Tenant:
    return tenant


def start_offboarding(tenant: Tenant, now: datetime) -> Tenant:
    return tenant


def complete_offboarding(tenant: Tenant, now: datetime, *, waived: bool = False) -> Tenant:
    return tenant


def purge_tenant(tenant: Tenant, now: datetime) -> Tenant:
    return tenant


def reopen_tenant(tenant: Tenant, now: datetime) -> Tenant:
    return tenant


def activate_tenant(tenant: Tenant, facts: ActivationFacts, now: datetime) -> Tenant:
    return tenant


def offboarding_may_complete_at(tenant: Tenant) -> datetime:
    return tenant.created_at


def number_quarantine_until(retired_at: datetime) -> datetime:
    return retired_at


def number_assignable(
    status: NumberStatus | None, quarantine_until: datetime | None, now: datetime
) -> bool:
    return True


def purge_blockers(
    tenant: Tenant, now: datetime, operator_refs: Sequence[str], typed_slug: str
) -> list[str]:
    return []


def activation_blockers(facts: ActivationFacts) -> list[str]:
    return []
