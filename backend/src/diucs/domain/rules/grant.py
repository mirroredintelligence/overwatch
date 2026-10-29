"""Grant rules (TEN-036). STUB (DEC-010, red commit): every rule raises NotImplementedError."""

from collections.abc import Sequence
from datetime import datetime

from diucs.domain.model.network import (
    Agreement,
    Grant,
    GrantApprover,
    GrantEndReason,
    GrantScope,
    GrantStatus,
    GrantPurpose,
    NetworkMembership,
)


def _todo() -> None:
    raise NotImplementedError


def transition_grant(current: GrantStatus, target: GrantStatus) -> GrantStatus:
    _todo()
    return target


def propose_grant(
    *,
    id: str,
    network_id: str,
    grantor_tenant_id: str,
    scope: GrantScope,
    purpose: GrantPurpose,
    effective_from: datetime,
    effective_to: datetime | None,
    agreement: Agreement,
    allowlist_version: int,
    proposed_by_account_ref: str,
    proposed_at: datetime,
) -> Grant:
    _todo()
    raise NotImplementedError


def approve_grant(
    grant: Grant,
    *,
    approver: GrantApprover,
    approver_tenant_id: str,
    network_owner_tenant_id: str,
    account_ref: str,
    now: datetime,
) -> Grant:
    _todo()
    return grant


def decline_grant(
    grant: Grant,
    *,
    by_tenant_id: str,
    network_owner_tenant_id: str,
    account_ref: str,
    now: datetime,
) -> Grant:
    _todo()
    return grant


def end_grant(grant: Grant, *, by_tenant_id: str, account_ref: str, now: datetime) -> Grant:
    _todo()
    return grant


def lapse_grant(grant: Grant, *, now: datetime) -> Grant:
    _todo()
    return grant


def lapse_grants_for_member(
    grants: Sequence[Grant], membership: NetworkMembership, *, now: datetime
) -> tuple[Grant, ...]:
    _todo()
    return tuple(grants)


def revise_grant(
    current: Grant,
    *,
    new_id: str,
    effective_from: datetime,
    effective_to: datetime | None,
    agreement: Agreement,
    allowlist_version: int,
    proposed_by_account_ref: str,
    now: datetime,
) -> Grant:
    _todo()
    return current


def supersede_grant(old: Grant, successor: Grant, *, now: datetime) -> Grant:
    _todo()
    return old


def is_effective(grant: Grant, now: datetime) -> bool:
    _todo()
    return False


def was_effective_at(grant: Grant, instant: datetime) -> bool:
    _todo()
    return False


def effective_grant(
    grants: Sequence[Grant],
    *,
    network_id: str,
    grantor_tenant_id: str,
    scope: GrantScope,
    now: datetime,
) -> Grant | None:
    _todo()
    return None


def may_project(grant: Grant, membership: NetworkMembership, now: datetime) -> bool:
    _todo()
    return False


def end_reason(grant: Grant) -> GrantEndReason | None:
    _todo()
    return None
