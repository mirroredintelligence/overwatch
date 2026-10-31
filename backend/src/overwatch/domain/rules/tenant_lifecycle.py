"""Tenant lifecycle state machine, activation blockers, number quarantine and purge rules (TEN-006).

Rules: docs/delivery/tenancy-audit/F-lifecycle-flows.md section 2.4, DEC-136 item 10, DEC-155.
The style is `rules/registration.py` (D22): lookups are keyed by exact enum members, every incoming
status is checked to be exactly a `TenantStatus` first (lesson L3: `"active"` and
`NumberStatus.ACTIVE` both equal `TenantStatus.ACTIVE`), and a refusal names the two statuses and
nothing else.

Pure: no I/O and no clock. Every instant is passed in; a naive or missing one is a `ValueError`,
as in `london_time.py`. Every move returns a new `Tenant` (a frozen value) through
`dataclasses.replace`, so the record's own invariants run again on the result.

Fail closed: an unknown status, an illegal move, a notice or hold that has not ended, a missing
fact or anything but the exact passing value is refused or listed as a blocker.
"""

import dataclasses
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from diucs.domain.errors import InvalidTransition, NotAllowed, ValidationFailed
from diucs.domain.model.tenant import (
    ALLOWED_TIME_ZONES,
    REQUIRED_RETENTION_CLASSES,
    ConfigStatus,
    ContactKind,
    NumberStatus,
    RetentionClass,
    SuspendMode,
    SuspendReason,
    Tenant,
    TenantStatus,
)
from diucs.domain.rules.tenant_settings import is_named_ref

# DEC-136 item 10.
OFFBOARDING_NOTICE: Final = timedelta(days=30)
# Audit C proposed 7 days earlier; DEC-136 is later and wins.
NUMBER_QUARANTINE: Final = timedelta(days=90)
PURGE_OPERATORS_REQUIRED: Final = 2
# The references an operator records for activation: a data sharing agreement, a data protection
# impact assessment and a clinical safety case. The system records that they were asserted.
REQUIRED_REFERENCES: Final = frozenset({"dsa", "dpia", "dcb0160"})

_T = TenantStatus
_C = ConfigStatus

# audit F section 2.4: the only legal moves. Everything else is refused. `purged` is terminal.
_ALLOWED: Final[Mapping[TenantStatus, frozenset[TenantStatus]]] = MappingProxyType(
    {
        _T.PROVISIONING: frozenset({_T.ACTIVE}),
        _T.ACTIVE: frozenset({_T.SUSPENDED, _T.OFFBOARDING}),
        _T.SUSPENDED: frozenset({_T.ACTIVE, _T.OFFBOARDING}),
        _T.OFFBOARDING: frozenset({_T.OFFBOARDED, _T.ACTIVE}),
        _T.OFFBOARDED: frozenset({_T.ACTIVE, _T.PURGED}),
        _T.PURGED: frozenset(),
    }
)
_CONFIG_ALLOWED: Final[Mapping[ConfigStatus, frozenset[ConfigStatus]]] = MappingProxyType(
    {
        _C.DRAFT: frozenset({_C.PENDING_APPROVAL}),
        _C.PENDING_APPROVAL: frozenset({_C.DRAFT, _C.CURRENT}),
        _C.CURRENT: frozenset({_C.SUPERSEDED}),
        _C.SUPERSEDED: frozenset(),
    }
)

TENANT_REQUIRED_MESSAGE: Final = "a Tenant is required"
NAIVE_INSTANT_MESSAGE: Final = "datetime must be timezone-aware (UTC)"
NOTICE_MESSAGE: Final = "the offboarding notice period has not ended"
NOT_STARTED_MESSAGE: Final = "offboarding has not started"
HOLD_MESSAGE: Final = "the retention hold has not passed"
FACTS_REQUIRED_MESSAGE: Final = "ActivationFacts are required"

# Purge blockers: fixed wording, fixed order.
BLOCKER_NOT_OFFBOARDED: Final = "Tenant is offboarded"
BLOCKER_HOLD: Final = "Retention hold has not passed"
BLOCKER_OPERATORS: Final = "Two different operators are needed"
BLOCKER_TYPED_ID: Final = "The tenant id was not typed correctly"

# Activation blockers (audit F section 2.4), in this order. They describe what is missing. The
# references are asserted by an operator, not proved: no sentence says approved or certified.
MISSING_CONFIG: Final = "Configuration version approved"
MISSING_ZONE: Final = "Time zone set"
MISSING_NUMBER: Final = "At least one sender number active with a test text delivered"
MISSING_EMAIL: Final = "Email sender verified"
MISSING_ADMIN: Final = "First tenant administrator invited"
MISSING_DIRECTORY: Final = "Sign-in directory bound and verified"
MISSING_ROLE: Final = "At least one role mapping"
MISSING_CONTACTS: Final = "Support contacts set: coordination phone and clinical safety officer"
MISSING_RETENTION: Final = "Retention set for every data class"
MISSING_REFERENCES: Final = "Data sharing, data protection and clinical safety references recorded"
MISSING_WORDING: Final = "System, referral system and coordination team names set"
MISSING_DISTRICTS: Final = "Area districts set"
MISSING_AGREEMENT: Final = "Network agreement accepted"


@dataclass(frozen=True, slots=True)
class ActivationFacts:
    """What the activating use case (TEN-028) knows about a provisioning tenant. Every field is
    required, none has a default: a fact nobody supplied cannot pass."""

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


# ---------------------------------------------------------------- argument checks


def _tenant(value: object) -> Tenant:
    if type(value) is not Tenant:
        raise TypeError(TENANT_REQUIRED_MESSAGE)
    return value


def _instant(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(NAIVE_INSTANT_MESSAGE)
    return value


def _status(value: object, field: str) -> TenantStatus:
    if type(value) is not TenantStatus:
        raise ValidationFailed(field, "not a tenant status")
    return value


# ---------------------------------------------------------------- the state machine


def transition_tenant(current: TenantStatus, target: TenantStatus) -> TenantStatus:
    """The target, when the move is one of the legal ones; otherwise `InvalidTransition`."""
    checked_current = _status(current, "current")
    checked_target = _status(target, "target")
    if checked_target not in _ALLOWED[checked_current]:
        raise InvalidTransition(
            f"tenant cannot move from {checked_current.value} to {checked_target.value}"
        )
    return checked_target


def transition_config(current: ConfigStatus, target: ConfigStatus) -> ConfigStatus:
    """The same for the status of a configuration version. A `current` version is never edited and
    never goes back to a draft: its successor supersedes it."""
    if type(current) is not ConfigStatus:
        raise ValidationFailed("current", "not a configuration status")
    if type(target) is not ConfigStatus:
        raise ValidationFailed("target", "not a configuration status")
    if target not in _CONFIG_ALLOWED[current]:
        raise InvalidTransition(f"configuration cannot move from {current.value} to {target.value}")
    return target


def _move(tenant: Tenant, target: TenantStatus, only_from: frozenset[TenantStatus]) -> None:
    """`transition_tenant` first, then the narrower rule of the function that asked: reopen,
    resume and activate are different moves to the same status."""
    transition_tenant(tenant.status, target)
    if tenant.status not in only_from:
        raise InvalidTransition(
            f"tenant cannot move from {tenant.status.value} to {target.value} this way"
        )


def suspend_tenant(
    tenant: Tenant, mode: SuspendMode, reason: SuspendReason, now: datetime
) -> Tenant:
    """Suspend an active tenant. The epoch goes up so that sessions issued before are refused."""
    checked = _tenant(tenant)
    instant = _instant(now)
    transition_tenant(checked.status, _T.SUSPENDED)
    return dataclasses.replace(
        checked,
        status=_T.SUSPENDED,
        suspend_mode=mode,
        suspend_reason=reason,
        suspended_at=instant,
        epoch=checked.epoch + 1,
    )


def resume_tenant(tenant: Tenant, now: datetime) -> Tenant:
    """Resume a suspended tenant: the three suspend fields are cleared and the epoch goes up."""
    checked = _tenant(tenant)
    _instant(now)
    _move(checked, _T.ACTIVE, frozenset({_T.SUSPENDED}))
    return dataclasses.replace(
        checked,
        status=_T.ACTIVE,
        suspend_mode=None,
        suspend_reason=None,
        suspended_at=None,
        epoch=checked.epoch + 1,
    )


def start_offboarding(tenant: Tenant, now: datetime) -> Tenant:
    """Start the notice period. A tenant that was suspended is no longer: the three suspend fields
    are cleared (how much access an offboarding tenant has is TEN-073's rule)."""
    checked = _tenant(tenant)
    instant = _instant(now)
    transition_tenant(checked.status, _T.OFFBOARDING)
    return dataclasses.replace(
        checked,
        status=_T.OFFBOARDING,
        offboarding_started_at=instant,
        suspend_mode=None,
        suspend_reason=None,
        suspended_at=None,
    )


def offboarding_may_complete_at(tenant: Tenant) -> datetime:
    """The first instant at which the notice period has ended."""
    started = _tenant(tenant).offboarding_started_at
    if started is None:
        raise NotAllowed(NOT_STARTED_MESSAGE)
    return started + OFFBOARDING_NOTICE


def complete_offboarding(tenant: Tenant, now: datetime, *, waived: bool = False) -> Tenant:
    """Finish offboarding. Before the notice has ended this is refused unless the tenant waived the
    notice in writing; `waived` is set by the use case, never read from a request, and only the
    value `True` waives it (anything else counts as not waived)."""
    checked = _tenant(tenant)
    instant = _instant(now)
    transition_tenant(checked.status, _T.OFFBOARDED)
    if waived is not True and instant < offboarding_may_complete_at(checked):
        raise NotAllowed(NOTICE_MESSAGE)
    return dataclasses.replace(checked, status=_T.OFFBOARDED, offboarded_at=instant)


def purge_tenant(tenant: Tenant, now: datetime) -> Tenant:
    """Mark an offboarded tenant purged, unless a retention hold is still in the future. Who may
    purge (two operators, the typed id) is `purge_blockers`; the deletion is TEN-074's."""
    checked = _tenant(tenant)
    instant = _instant(now)
    transition_tenant(checked.status, _T.PURGED)
    hold = checked.retention_hold_until
    if hold is not None and hold > instant:
        raise NotAllowed(HOLD_MESSAGE)
    return dataclasses.replace(checked, status=_T.PURGED, purged_at=instant)


def reopen_tenant(tenant: Tenant) -> Tenant:
    """Reopen an offboarding or offboarded tenant before it is purged (audit F section 2.4). The
    offboarding timestamps are cleared, so a later offboarding starts a new notice period, and the
    epoch goes up."""
    checked = _tenant(tenant)
    _move(checked, _T.ACTIVE, frozenset({_T.OFFBOARDING, _T.OFFBOARDED}))
    return dataclasses.replace(
        checked,
        status=_T.ACTIVE,
        offboarding_started_at=None,
        offboarded_at=None,
        epoch=checked.epoch + 1,
    )


def activate_tenant(tenant: Tenant, facts: ActivationFacts, now: datetime) -> Tenant:
    """Activate a provisioning tenant. The state is checked first, then the facts: any blocker
    refuses the move. The sentences are fixed wording and name nothing about the tenant."""
    checked = _tenant(tenant)
    instant = _instant(now)
    if type(facts) is not ActivationFacts:
        raise TypeError(FACTS_REQUIRED_MESSAGE)
    _move(checked, _T.ACTIVE, frozenset({_T.PROVISIONING}))
    blockers = activation_blockers(facts)
    if blockers:
        raise NotAllowed("Activation is unavailable until: " + "; ".join(blockers))
    return dataclasses.replace(checked, status=_T.ACTIVE, activated_at=instant)


# ---------------------------------------------------------------- numbers and purge


def number_quarantine_until(retired_at: datetime) -> datetime:
    """A retired number may not be given to another tenant until this instant."""
    return _instant(retired_at) + NUMBER_QUARANTINE


def number_assignable(
    status: NumberStatus | None, quarantine_until: datetime | None, now: datetime
) -> bool:
    """May this number be given to a tenant now? `None` is a number that was never assigned. An
    active number is in use. A retired or quarantined number needs its quarantine end, and `now`
    at or after it; with no end on record it is not assignable (fail closed)."""
    instant = _instant(now)
    end = None if quarantine_until is None else _instant(quarantine_until)
    if status is None:
        return True
    if type(status) is not NumberStatus:
        raise ValidationFailed("status", "not a number status")
    if status is NumberStatus.ACTIVE or end is None:
        return False
    return instant >= end


def purge_blockers(
    tenant: Tenant, now: datetime, operator_refs: Sequence[str], typed_slug: str
) -> list[str]:
    """Why this tenant may not be purged yet. Fixed wording, fixed order; empty means it may."""
    checked = _tenant(tenant)
    instant = _instant(now)
    blockers: list[str] = []
    if checked.status is not _T.OFFBOARDED:
        blockers.append(BLOCKER_NOT_OFFBOARDED)
    hold = checked.retention_hold_until
    if hold is not None and hold > instant:
        blockers.append(BLOCKER_HOLD)
    if _distinct_operators(operator_refs) < PURGE_OPERATORS_REQUIRED:
        blockers.append(BLOCKER_OPERATORS)
    if type(typed_slug) is not str or typed_slug != checked.id:
        blockers.append(BLOCKER_TYPED_ID)
    return blockers


def _distinct_operators(refs: object) -> int:
    """How many different, named operators there are. A bare string, or anything that is not a
    list or tuple, counts as none."""
    if isinstance(refs, str) or not isinstance(refs, Sequence):
        return 0
    return len({ref for ref in refs if is_named_ref(ref)})


# ---------------------------------------------------------------- activation blockers


def _exact_members(values: object, enum_type: type[StrEnum]) -> frozenset[object]:
    """The members of a set that are exactly of the enum type: plain text that equals a member does
    not count (lesson L3)."""
    if not isinstance(values, frozenset):
        return frozenset()
    return frozenset(value for value in values if type(value) is enum_type)


def _plain_strings(values: object) -> frozenset[object]:
    if not isinstance(values, frozenset):
        return frozenset()
    return frozenset(value for value in values if type(value) is str)


def _at_least_one(count: object) -> bool:
    return type(count) is int and count >= 1


def activation_blockers(facts: ActivationFacts) -> list[str]:
    """One fixed sentence for each check that is not met, in a fixed order. Each test is `is not
    True` or an exact membership, so anything other than the passing value counts as missing."""
    missing: list[str] = []
    if facts.config_approved is not True:
        missing.append(MISSING_CONFIG)
    if type(facts.time_zone) is not str or facts.time_zone not in ALLOWED_TIME_ZONES:
        missing.append(MISSING_ZONE)
    if not _at_least_one(facts.active_numbers_tested):
        missing.append(MISSING_NUMBER)
    # Email is checked unless it is exactly not in use.
    if facts.email_in_use is not False and facts.email_sender_verified is not True:
        missing.append(MISSING_EMAIL)
    if facts.first_admin_invited is not True:
        missing.append(MISSING_ADMIN)
    if facts.entra_binding_verified is not True:
        missing.append(MISSING_DIRECTORY)
    if not _at_least_one(facts.role_mappings):
        missing.append(MISSING_ROLE)
    contacts = _exact_members(facts.contact_kinds, ContactKind)
    if not {ContactKind.COORDINATION_PHONE, ContactKind.CLINICAL_SAFETY_OFFICER} <= contacts:
        missing.append(MISSING_CONTACTS)
    retention = _exact_members(facts.retention_classes_set, RetentionClass)
    if not retention >= REQUIRED_RETENTION_CLASSES:
        missing.append(MISSING_RETENTION)
    if not _plain_strings(facts.references_recorded) >= REQUIRED_REFERENCES:
        missing.append(MISSING_REFERENCES)
    if facts.wording_complete is not True:
        missing.append(MISSING_WORDING)
    if facts.registers_services is not False and facts.area_districts_set is not True:
        missing.append(MISSING_DISTRICTS)
    if facts.network_member is not False and facts.agreement_accepted is not True:
        missing.append(MISSING_AGREEMENT)
    return missing
