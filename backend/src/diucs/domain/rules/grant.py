"""Grant rules: propose, approve, decline, end, lapse, revise, supersede, and whether a grant is
effective (TEN-036; DEC-132 items 3 and 6, DEC-134 item 6, DEC-136 item 4).

A grant is the only way data is shared. Its effectiveness is computed from the approvals, the
status and the window at the instant asked (`is_effective`), never read from a stored flag. Pure:
no I/O and no clock; every instant is an argument. Each rule that changes a grant returns a new
grant; nothing is edited in place.

Party rules: the grantor's approval and any decision by the grantor come from the grantor tenant;
the owner's approval comes from the network owner tenant; ending belongs to the grantor alone
(the owner removes a member, it does not end a member's grant). Refusals name the field and
never the value.
"""

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from diucs.domain.errors import Conflict, InvalidTransition, NotAllowed, ValidationFailed
from diucs.domain.model.network import (
    ACCOUNT_REF_PATTERN,
    Agreement,
    Approval,
    Grant,
    GrantApprover,
    GrantEndReason,
    GrantPurpose,
    GrantScope,
    GrantStatus,
    MembershipStatus,
    NetworkMembership,
    check_network_id,
    check_tenant_field,
)

_G = GrantStatus

# domain-rules and DEC-132: the only legal moves. Everything else is InvalidTransition.
_ALLOWED: Mapping[GrantStatus, frozenset[GrantStatus]] = MappingProxyType(
    {
        _G.PROPOSED: frozenset(
            {_G.GRANTOR_APPROVED, _G.OWNER_APPROVED, _G.DECLINED, _G.ENDED, _G.LAPSED}
        ),
        _G.GRANTOR_APPROVED: frozenset({_G.APPROVED, _G.DECLINED, _G.ENDED, _G.LAPSED}),
        _G.OWNER_APPROVED: frozenset({_G.APPROVED, _G.DECLINED, _G.ENDED, _G.LAPSED}),
        _G.APPROVED: frozenset({_G.ENDED, _G.LAPSED, _G.SUPERSEDED}),
        _G.DECLINED: frozenset(),
        _G.ENDED: frozenset(),
        _G.LAPSED: frozenset(),
        _G.SUPERSEDED: frozenset(),
    }
)
_TERMINAL: Final = frozenset({_G.DECLINED, _G.ENDED, _G.LAPSED, _G.SUPERSEDED})
_NON_TERMINAL: Final = frozenset({_G.PROPOSED, _G.GRANTOR_APPROVED, _G.OWNER_APPROVED, _G.APPROVED})
_HISTORY: Final = frozenset({_G.APPROVED, _G.ENDED, _G.LAPSED, _G.SUPERSEDED})
_END_REASON: Final = MappingProxyType(
    {
        _G.ENDED: GrantEndReason.ENDED,
        _G.LAPSED: GrantEndReason.LAPSED,
        _G.SUPERSEDED: GrantEndReason.SUPERSEDED,
    }
)

MIN_VERSION: Final = 1
NOT_BACKDATED_MESSAGE: Final = "must not be earlier than the moment it is proposed"
NOT_AN_ACCOUNT_MESSAGE: Final = "is not a valid account reference"
ENUM_MESSAGE: Final = "is not a valid value for this field"
RECORD_MESSAGE: Final = "is not the right kind of record"
AWARE_MESSAGE: Final = "must be a timezone-aware datetime"


def _checked(value: object, enum_cls: type[StrEnum], field: str) -> None:
    # `type(...) is` refuses a plain string and a member of another enum with the same value.
    if type(value) is not enum_cls:
        raise ValidationFailed(field, ENUM_MESSAGE)


def _record(value: object, record: type, field: str) -> None:
    if type(value) is not record:
        raise ValidationFailed(field, RECORD_MESSAGE)


def _aware(value: object, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValidationFailed(field, AWARE_MESSAGE)
    return value


def _account(value: object, field: str) -> str:
    if type(value) is not str or ACCOUNT_REF_PATTERN.fullmatch(value) is None:
        raise ValidationFailed(field, NOT_AN_ACCOUNT_MESSAGE)
    return value


def _utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


def _version(value: object, field: str) -> int:
    if type(value) is not int or value < MIN_VERSION:
        raise ValidationFailed(field, "must be a whole number of at least 1")
    return value


def transition_grant(current: GrantStatus, target: GrantStatus) -> GrantStatus:
    _checked(current, GrantStatus, "current")
    _checked(target, GrantStatus, "target")
    if target not in _ALLOWED[current]:
        raise InvalidTransition(f"grant cannot move from {current.value} to {target.value}")
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
    """A proposed grant, version 1, with no approvals. Sharing is never backdated: the start may
    not be before the proposal. The end, when given, is after the start (the record checks it)."""
    _checked(scope, GrantScope, "scope")
    _checked(purpose, GrantPurpose, "purpose")
    _aware(proposed_at, "proposed_at")
    _aware(effective_from, "effective_from")
    if _utc(effective_from) < _utc(proposed_at):
        raise ValidationFailed("effective_from", NOT_BACKDATED_MESSAGE)
    return Grant(
        id=id,
        network_id=network_id,
        grantor_tenant_id=grantor_tenant_id,
        scope=scope,
        purpose=purpose,
        version=MIN_VERSION,
        status=_G.PROPOSED,
        effective_from=effective_from,
        effective_to=effective_to,
        agreement=agreement,
        allowlist_version=allowlist_version,
        proposed_by_account_ref=proposed_by_account_ref,
        proposed_at=proposed_at,
        grantor_approval=None,
        owner_approval=None,
        ended_at=None,
        ended_by_account_ref=None,
        supersedes_id=None,
    )


def approve_grant(
    grant: Grant,
    *,
    approver: GrantApprover,
    approver_tenant_id: str,
    network_owner_tenant_id: str,
    account_ref: str,
    now: datetime,
) -> Grant:
    """One party's approval. The two approvals may come in either order; the grant is approved when
    both are in. The same account again for the same party returns the grant unchanged; a different
    account for that party is a conflict. When the grantor and the owner are one tenant, the two
    approvals still need two different accounts (two people)."""
    _record(grant, Grant, "grant")
    _checked(approver, GrantApprover, "approver")
    check_tenant_field(approver_tenant_id, "approver_tenant_id")
    check_tenant_field(network_owner_tenant_id, "network_owner_tenant_id")
    _account(account_ref, "account_ref")
    _aware(now, "now")
    if grant.status in _TERMINAL:
        raise InvalidTransition("an ended grant cannot be approved")
    if approver is GrantApprover.GRANTOR:
        if approver_tenant_id != grant.grantor_tenant_id:
            raise NotAllowed("the grantor's approval must come from the grantor organisation")
        mine, other = grant.grantor_approval, grant.owner_approval
    else:
        if approver_tenant_id != network_owner_tenant_id:
            raise NotAllowed("the owner's approval must come from the network owner")
        mine, other = grant.owner_approval, grant.grantor_approval
    if mine is not None:
        if mine.account_ref == account_ref:
            return grant
        raise Conflict("this party has already approved the grant")
    if other is not None and other.account_ref == account_ref:
        raise Conflict("the same account cannot give both approvals")
    record = Approval(account_ref=account_ref, tenant_id=approver_tenant_id, at=now)
    if approver is GrantApprover.GRANTOR:
        target = _G.APPROVED if other is not None else _G.GRANTOR_APPROVED
        return replace(
            grant, status=transition_grant(grant.status, target), grantor_approval=record
        )
    target = _G.APPROVED if other is not None else _G.OWNER_APPROVED
    return replace(grant, status=transition_grant(grant.status, target), owner_approval=record)


def decline_grant(
    grant: Grant,
    *,
    by_tenant_id: str,
    network_owner_tenant_id: str,
    account_ref: str,
    now: datetime,
) -> Grant:
    """Either party may decline before approval. After approval, only ending applies."""
    _record(grant, Grant, "grant")
    check_tenant_field(by_tenant_id, "by_tenant_id")
    check_tenant_field(network_owner_tenant_id, "network_owner_tenant_id")
    _account(account_ref, "account_ref")
    _aware(now, "now")
    transition_grant(grant.status, _G.DECLINED)
    if by_tenant_id not in (grant.grantor_tenant_id, network_owner_tenant_id):
        raise NotAllowed("only the grantor or the network owner can decline")
    return replace(grant, status=_G.DECLINED, ended_at=now)


def end_grant(grant: Grant, *, by_tenant_id: str, account_ref: str, now: datetime) -> Grant:
    """The grantor ends its grant. Future sharing stops; approvals and the window are kept, so the
    history still shows what was shared. Ending an ended grant returns it unchanged (a retry)."""
    _record(grant, Grant, "grant")
    check_tenant_field(by_tenant_id, "by_tenant_id")
    _account(account_ref, "account_ref")
    _aware(now, "now")
    if by_tenant_id != grant.grantor_tenant_id:
        raise NotAllowed("only the grantor can end a grant")
    if grant.status is _G.ENDED:
        return grant
    transition_grant(grant.status, _G.ENDED)
    return replace(grant, status=_G.ENDED, ended_at=now, ended_by_account_ref=account_ref)


def lapse_grant(grant: Grant, *, now: datetime) -> Grant:
    _record(grant, Grant, "grant")
    _aware(now, "now")
    transition_grant(grant.status, _G.LAPSED)
    return replace(grant, status=_G.LAPSED, ended_at=now)


def lapse_grants_for_member(
    grants: Sequence[Grant], membership: NetworkMembership, *, now: datetime
) -> tuple[Grant, ...]:
    """The lapsed copies of the member's live grants in its network. Terminal grants, other members'
    grants and other networks' grants are not returned and not changed."""
    _record(membership, NetworkMembership, "membership")
    _aware(now, "now")
    lapsed: list[Grant] = []
    for grant in grants:
        _record(grant, Grant, "grants")
        if (
            grant.network_id == membership.network_id
            and grant.grantor_tenant_id == membership.member_tenant_id
            and grant.status in _NON_TERMINAL
        ):
            lapsed.append(lapse_grant(grant, now=now))
    return tuple(lapsed)


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
    """A new proposed grant that replaces an approved one at the next version. The scope, purpose,
    grantor and network are the same. Widening the allowlist needs a higher agreement version."""
    _record(current, Grant, "current")
    _record(agreement, Agreement, "agreement")
    _version(allowlist_version, "allowlist_version")
    _account(proposed_by_account_ref, "proposed_by_account_ref")
    _aware(now, "now")
    if current.status is not _G.APPROVED:
        raise InvalidTransition("only an approved grant can be revised")
    if (
        allowlist_version > current.allowlist_version
        and agreement.version <= current.agreement.version
    ):
        raise ValidationFailed("agreement", "a wider allowlist needs a newer agreement version")
    if _utc(_aware(effective_from, "effective_from")) < _utc(now):
        raise ValidationFailed("effective_from", NOT_BACKDATED_MESSAGE)
    return Grant(
        id=new_id,
        network_id=current.network_id,
        grantor_tenant_id=current.grantor_tenant_id,
        scope=current.scope,
        purpose=current.purpose,
        version=current.version + 1,
        status=_G.PROPOSED,
        effective_from=effective_from,
        effective_to=effective_to,
        agreement=agreement,
        allowlist_version=allowlist_version,
        proposed_by_account_ref=proposed_by_account_ref,
        proposed_at=now,
        grantor_approval=None,
        owner_approval=None,
        ended_at=None,
        ended_by_account_ref=None,
        supersedes_id=current.id,
    )


def supersede_grant(old: Grant, successor: Grant, *, now: datetime) -> Grant:
    """The approved `old` grant ends where the approved `successor` starts. From the successor's
    start, only the successor is effective: there is no overlap and no gap."""
    _record(old, Grant, "old")
    _record(successor, Grant, "successor")
    _aware(now, "now")
    transition_grant(old.status, _G.SUPERSEDED)
    if successor.status is not _G.APPROVED:
        raise Conflict("the successor grant is not approved")
    if successor.version != old.version + 1 or successor.supersedes_id != old.id:
        raise Conflict("the successor does not follow this grant")
    lineage_old = (old.network_id, old.grantor_tenant_id, old.scope, old.purpose)
    lineage_new = (
        successor.network_id,
        successor.grantor_tenant_id,
        successor.scope,
        successor.purpose,
    )
    if lineage_old != lineage_new:
        raise ValidationFailed("successor", "is for another grant lineage")
    start = _utc(successor.effective_from)
    if _utc(now) < start:
        raise Conflict("the successor has not started")
    if start <= _utc(old.effective_from):
        raise Conflict("the successor must start after this grant")
    if old.effective_to is not None and _utc(old.effective_to) < start:
        raise Conflict("a gap would be left between the two grants")
    return replace(old, status=_G.SUPERSEDED, ended_at=now, effective_to=successor.effective_from)


def is_effective(grant: Grant, now: datetime) -> bool:
    """The only definition of "effective": approved, both approvals in, not ended, and the instant
    is in the window (start inclusive, end exclusive, compared in UTC)."""
    _record(grant, Grant, "grant")
    _aware(now, "now")
    if grant.status is not _G.APPROVED:
        return False
    if grant.grantor_approval is None or grant.owner_approval is None:
        return False
    if grant.ended_at is not None:
        return False
    at = _utc(now)
    if at < _utc(grant.effective_from):
        return False
    if grant.effective_to is None:
        return True
    return at < _utc(grant.effective_to)


def was_effective_at(grant: Grant, instant: datetime) -> bool:
    """For history: was the grant in effect at the instant? The window ends at the earlier of the
    end date and the moment it was ended. A grant that never had both approvals never was."""
    _record(grant, Grant, "grant")
    _aware(instant, "instant")
    if grant.grantor_approval is None or grant.owner_approval is None:
        return False
    if grant.status not in _HISTORY:
        return False
    at = _utc(instant)
    if at < _utc(grant.effective_from):
        return False
    ends = [_utc(value) for value in (grant.effective_to, grant.ended_at) if value is not None]
    if not ends:
        return True
    return at < min(ends)


def effective_grant(
    grants: Sequence[Grant],
    *,
    network_id: str,
    grantor_tenant_id: str,
    scope: GrantScope,
    now: datetime,
) -> Grant | None:
    """The effective grant with the highest version for this member and scope, or None."""
    check_network_id(network_id, "network_id")
    check_tenant_field(grantor_tenant_id, "grantor_tenant_id")
    _checked(scope, GrantScope, "scope")
    _aware(now, "now")
    best: Grant | None = None
    for grant in grants:
        _record(grant, Grant, "grants")
        if (
            grant.network_id == network_id
            and grant.grantor_tenant_id == grantor_tenant_id
            and grant.scope is scope
            and is_effective(grant, now)
            and (best is None or grant.version > best.version)
        ):
            best = grant
    return best


def may_project(grant: Grant, membership: NetworkMembership, now: datetime) -> bool:
    """The projector's gate (TEN-054): the grant is effective, the membership is active and not
    left, and both belong to the grantor's organisation and this network."""
    _record(grant, Grant, "grant")
    _record(membership, NetworkMembership, "membership")
    _checked(membership.status, MembershipStatus, "membership")
    _aware(now, "now")
    return (
        is_effective(grant, now)
        and membership.status is MembershipStatus.ACTIVE
        and membership.left_at is None
        and membership.member_tenant_id == grant.grantor_tenant_id
        and membership.network_id == grant.network_id
    )


def end_reason(grant: Grant) -> GrantEndReason | None:
    _record(grant, Grant, "grant")
    _checked(grant.status, GrantStatus, "status")
    return _END_REASON.get(grant.status)
