"""Network domain model: networks, memberships, grants and listings (TEN-036).

DEC-132 (a network is a group of tenants; sharing only through a grant and a read-only projection),
DEC-134 item 6 (whether a grant is effective is computed, never stored), DEC-136 item 3 (listings
are admitted by the network owner). Pure: no I/O and no clock; every instant is an argument.

Fail closed: every enum argument is checked by its exact type (lessons L3 and L38), every datetime
must be timezone-aware, every tenant id goes through `check_tenant_id` (TEN-006), and every network
id goes through the network pattern (the same one as TEN-001's `ScopeId.network`). Refusals name the
field and never the value. Instants are compared in UTC: two aware datetimes that share one zone
object compare wall-clock time (lesson L4).

The rules that change a grant are in `rules/grant.py`; the listing rules are in `rules/listing.py`.
"""

import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from diucs.domain.errors import Conflict, InvalidTransition, NotAllowed, ValidationFailed
from diucs.domain.messages.privacy_guard import find_patient_data
from diucs.domain.model.tenant import RESERVED_TENANT_PREFIX, check_tenant_id

# ---------------------------------------------------------------- identifiers

NETWORK_ID_PREFIX: Final = RESERVED_TENANT_PREFIX
# `net-` and 1 to 26 more characters of lower case letters, digits and hyphen (6 to 31 in all).
# The same pattern as TEN-001's `ScopeId.network` (a parity test keeps them equal).
NETWORK_ID_PATTERN: Final = re.compile(r"net-[a-z0-9][a-z0-9-]{1,26}")
RECORD_ID_PATTERN: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
# An opaque id from the verified identity (an HMAC): never a name or an e-mail (DEC-132 item 2).
ACCOUNT_REF_PATTERN: Final = re.compile(r"[A-Za-z0-9_-]{8,128}")
AGREEMENT_REFERENCE_PATTERN: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,63}")
NAME_MAX_LENGTH: Final = 80
MIN_VERSION: Final = 1

NETWORK_ID_MESSAGE: Final = "is not a valid network id"
TENANT_MESSAGE: Final = "is not a valid tenant id"
RECORD_ID_MESSAGE: Final = "is not a valid id"
ACCOUNT_MESSAGE: Final = "is not a valid account reference"
AWARE_MESSAGE: Final = "must be a timezone-aware datetime"
ENUM_MESSAGE: Final = "is not a valid value for this field"
TEXT_MESSAGE: Final = "is not valid text for this field"
REFERENCE_MESSAGE: Final = "is not a valid agreement reference"
VERSION_MESSAGE: Final = "must be a whole number of at least 1"
AGREEMENT_MESSAGE: Final = "is not an agreement"
MISMATCH_MESSAGE: Final = "does not match the status"


# ---------------------------------------------------------------- enums


class GrantScope(StrEnum):
    CAPACITY = "capacity"
    DIRECTORY = "directory"
    CRITERIA = "criteria"


class GrantPurpose(StrEnum):
    """DEC-132 item 3. Adding a purpose is a new decision: there is no "other"."""

    NETWORK_CAPACITY_VIEW = "network-capacity-view"


class GrantStatus(StrEnum):
    """No `effective` status is stored: effectiveness is computed (`rules/grant.py`)."""

    PROPOSED = "proposed"
    GRANTOR_APPROVED = "grantor-approved"
    OWNER_APPROVED = "owner-approved"
    APPROVED = "approved"
    DECLINED = "declined"
    ENDED = "ended"
    LAPSED = "lapsed"
    SUPERSEDED = "superseded"


class GrantApprover(StrEnum):
    GRANTOR = "grantor"
    OWNER = "owner"


class GrantEndReason(StrEnum):
    ENDED = "ended"
    LAPSED = "lapsed"
    SUPERSEDED = "superseded"


class NetworkStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CLOSED = "closed"


class MembershipStatus(StrEnum):
    INVITED = "invited"
    ACTIVE = "active"
    LEFT = "left"
    REMOVED = "removed"


class MembershipRole(StrEnum):
    OWNER = "owner"
    MEMBER = "member"


class MembershipEndReason(StrEnum):
    LEFT = "left"
    REMOVED = "removed"


class ListingStatus(StrEnum):
    PENDING = "pending"
    ADMITTED = "admitted"
    DECLINED = "declined"
    SUSPENDED = "suspended"
    WITHDRAWN = "withdrawn"


class ListingReason(StrEnum):
    """A code from a fixed list, never free text (DEC-136 item 3)."""

    OUTSIDE_AREA = "outside-area"
    OUTSIDE_PILOT = "outside-pilot"
    DUPLICATE_LISTING = "duplicate-listing"
    DATA_QUALITY = "data-quality"
    SAFETY_CONCERN = "safety-concern"
    AGREEMENT_BREACH = "agreement-breach"
    OTHER = "other"


class DirectorySource(StrEnum):
    """Where a directory entry came from (DEC-132 item 7): manual today."""

    MANUAL = "manual"
    DIRECTORY_OF_SERVICES = "directory-of-services"


# ---------------------------------------------------------------- shared checks


def _enum(value: object, enum_cls: type[StrEnum], field: str) -> None:
    # `type(...) is` refuses a plain string and a member of another enum with the same value.
    if type(value) is not enum_cls:
        raise ValidationFailed(field, ENUM_MESSAGE)


def _aware(value: object, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValidationFailed(field, AWARE_MESSAGE)
    return value


def _optional_aware(value: object, field: str) -> None:
    if value is not None:
        _aware(value, field)


def _utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


def _record_id(value: object, field: str) -> str:
    if type(value) is not str or RECORD_ID_PATTERN.fullmatch(value) is None:
        raise ValidationFailed(field, RECORD_ID_MESSAGE)
    return value


def _account_ref(value: object, field: str) -> str:
    if type(value) is not str or ACCOUNT_REF_PATTERN.fullmatch(value) is None:
        raise ValidationFailed(field, ACCOUNT_MESSAGE)
    return value


def _optional_account_ref(value: object, field: str) -> None:
    if value is not None:
        _account_ref(value, field)


def _record_type(value: object, record: type, field: str) -> None:
    if type(value) is not record:
        raise ValidationFailed(field, AGREEMENT_MESSAGE)


def check_tenant_field(value: object, field: str) -> str:
    """TEN-006's `check_tenant_id`, re-raised under the given field name, so that an error names
    `owner_tenant_id` and not `tenant_id`. The value is never echoed."""
    try:
        return check_tenant_id(value)
    except ValidationFailed:
        raise ValidationFailed(field, TENANT_MESSAGE) from None


def check_network_id(value: object, field: str = "network_id") -> str:
    """The value, when it is exactly a `str` that fullmatches the network pattern."""
    if type(value) is not str or NETWORK_ID_PATTERN.fullmatch(value) is None:
        raise ValidationFailed(field, NETWORK_ID_MESSAGE)
    return value


# ---------------------------------------------------------------- records


@dataclass(frozen=True, slots=True)
class Agreement:
    """The data sharing agreement, by its reference in the owner's own document system and its
    version. The agreement's content is never stored (DEC-132 item 2): there is no field for it."""

    reference: str
    version: int

    def __post_init__(self) -> None:
        if (
            type(self.reference) is not str
            or AGREEMENT_REFERENCE_PATTERN.fullmatch(self.reference) is None
            or find_patient_data(self.reference)
        ):
            raise ValidationFailed("reference", REFERENCE_MESSAGE)
        if type(self.version) is not int or self.version < MIN_VERSION:
            raise ValidationFailed("version", VERSION_MESSAGE)


@dataclass(frozen=True, slots=True)
class Approval:
    """One party's approval of a grant: who (an opaque account, and its tenant) and when."""

    account_ref: str
    tenant_id: str
    at: datetime

    def __post_init__(self) -> None:
        _account_ref(self.account_ref, "account_ref")
        check_tenant_field(self.tenant_id, "tenant_id")
        _aware(self.at, "at")


@dataclass(frozen=True, slots=True)
class Network:
    id: str
    name: str
    owner_tenant_id: str
    status: NetworkStatus
    agreement: Agreement | None
    created_at: datetime
    closed_at: datetime | None

    def __post_init__(self) -> None:
        check_network_id(self.id, "id")
        if (
            type(self.name) is not str
            or not 1 <= len(self.name) <= NAME_MAX_LENGTH
            or find_patient_data(self.name)
        ):
            raise ValidationFailed("name", TEXT_MESSAGE)
        check_tenant_field(self.owner_tenant_id, "owner_tenant_id")
        _enum(self.status, NetworkStatus, "status")
        if self.agreement is not None:
            _record_type(self.agreement, Agreement, "agreement")
        _aware(self.created_at, "created_at")
        _optional_aware(self.closed_at, "closed_at")
        if self.status is NetworkStatus.ACTIVE and self.agreement is None:
            raise ValidationFailed("agreement", MISMATCH_MESSAGE)
        if self.status is NetworkStatus.CLOSED and self.closed_at is None:
            raise ValidationFailed("closed_at", MISMATCH_MESSAGE)
        if self.status is not NetworkStatus.CLOSED and self.closed_at is not None:
            raise ValidationFailed("closed_at", MISMATCH_MESSAGE)


@dataclass(frozen=True, slots=True)
class NetworkMembership:
    """One tenant's membership of one network. A tenant that rejoins has a new row; a closed row
    is never reopened, so its leave date stays (DEC-132 item 6)."""

    id: str
    network_id: str
    member_tenant_id: str
    role: MembershipRole
    status: MembershipStatus
    invited_at: datetime
    joined_at: datetime | None
    left_at: datetime | None
    end_reason: MembershipEndReason | None
    accepted_agreement: Agreement | None

    def __post_init__(self) -> None:
        _record_id(self.id, "id")
        check_network_id(self.network_id, "network_id")
        check_tenant_field(self.member_tenant_id, "member_tenant_id")
        _enum(self.role, MembershipRole, "role")
        _enum(self.status, MembershipStatus, "status")
        _aware(self.invited_at, "invited_at")
        _optional_aware(self.joined_at, "joined_at")
        _optional_aware(self.left_at, "left_at")
        if self.end_reason is not None:
            _enum(self.end_reason, MembershipEndReason, "end_reason")
        if self.accepted_agreement is not None:
            _record_type(self.accepted_agreement, Agreement, "accepted_agreement")
        if (
            self.joined_at is not None
            and self.left_at is not None
            and _utc(self.left_at) < _utc(self.joined_at)
        ):
            raise ValidationFailed("left_at", MISMATCH_MESSAGE)
        _check_membership_status(self)


def _check_membership_status(row: NetworkMembership) -> None:
    status = row.status
    if status is MembershipStatus.INVITED:
        ok = row.joined_at is None and row.left_at is None and row.end_reason is None
        ok = ok and row.accepted_agreement is None
    elif status is MembershipStatus.ACTIVE:
        ok = row.joined_at is not None and row.left_at is None and row.end_reason is None
    elif status is MembershipStatus.LEFT:
        ok = (
            row.joined_at is not None
            and row.left_at is not None
            and row.end_reason is MembershipEndReason.LEFT
        )
    else:  # REMOVED: the only status left after the four are named (a removed row may never
        # have joined, so joined_at is not required)
        ok = row.left_at is not None and row.end_reason is MembershipEndReason.REMOVED
    if not ok:
        raise ValidationFailed("status", MISMATCH_MESSAGE)


@dataclass(frozen=True, slots=True)
class Grant:
    """One grant of one scope by one member, for the network's purpose. Its approvals and end
    fields must agree with its status (checked here)."""

    id: str
    network_id: str
    grantor_tenant_id: str
    scope: GrantScope
    purpose: GrantPurpose
    version: int
    status: GrantStatus
    effective_from: datetime
    effective_to: datetime | None
    agreement: Agreement
    allowlist_version: int
    proposed_by_account_ref: str
    proposed_at: datetime
    grantor_approval: Approval | None
    owner_approval: Approval | None
    ended_at: datetime | None
    ended_by_account_ref: str | None
    supersedes_id: str | None

    def __post_init__(self) -> None:
        _record_id(self.id, "id")
        check_network_id(self.network_id, "network_id")
        check_tenant_field(self.grantor_tenant_id, "grantor_tenant_id")
        _enum(self.scope, GrantScope, "scope")
        _enum(self.purpose, GrantPurpose, "purpose")
        _enum(self.status, GrantStatus, "status")
        _record_type(self.agreement, Agreement, "agreement")
        if type(self.version) is not int or self.version < MIN_VERSION:
            raise ValidationFailed("version", VERSION_MESSAGE)
        if type(self.allowlist_version) is not int or self.allowlist_version < MIN_VERSION:
            raise ValidationFailed("allowlist_version", VERSION_MESSAGE)
        _aware(self.effective_from, "effective_from")
        if self.effective_to is not None:
            _aware(self.effective_to, "effective_to")
            if _utc(self.effective_to) <= _utc(self.effective_from):
                raise ValidationFailed("effective_to", MISMATCH_MESSAGE)
        _account_ref(self.proposed_by_account_ref, "proposed_by_account_ref")
        _aware(self.proposed_at, "proposed_at")
        if self.grantor_approval is not None:
            _record_type(self.grantor_approval, Approval, "grantor_approval")
            if self.grantor_approval.tenant_id != self.grantor_tenant_id:
                raise ValidationFailed("grantor_approval", MISMATCH_MESSAGE)
        if self.owner_approval is not None:
            _record_type(self.owner_approval, Approval, "owner_approval")
        _optional_aware(self.ended_at, "ended_at")
        _optional_account_ref(self.ended_by_account_ref, "ended_by_account_ref")
        if self.supersedes_id is not None:
            _record_id(self.supersedes_id, "supersedes_id")
            if self.supersedes_id == self.id:
                raise ValidationFailed("supersedes_id", MISMATCH_MESSAGE)
        _check_grant_status(self)


def _check_grant_status(grant: Grant) -> None:
    status = grant.status
    has_grantor = grant.grantor_approval is not None
    has_owner = grant.owner_approval is not None
    ended = grant.ended_at is not None
    if status is GrantStatus.PROPOSED:
        ok = not has_grantor and not has_owner and not ended
    elif status is GrantStatus.GRANTOR_APPROVED:
        ok = has_grantor and not has_owner and not ended
    elif status is GrantStatus.OWNER_APPROVED:
        ok = has_owner and not has_grantor and not ended
    elif status is GrantStatus.APPROVED:
        ok = has_grantor and has_owner and not ended
    else:  # ENDED, DECLINED, LAPSED, SUPERSEDED: all of them carry the end date
        ok = ended
    # Only ending names a person: an ended grant names who ended it, and no other grant does.
    names_ender = grant.ended_by_account_ref is not None
    if names_ender != (status is GrantStatus.ENDED):
        ok = False
    if not ok:
        raise ValidationFailed("status", MISMATCH_MESSAGE)


@dataclass(frozen=True, slots=True)
class Listing:
    """One member's service, offered to the network. Keyed by (network, source tenant, service):
    a member has at most one live listing per service (hazard H-N12)."""

    id: str
    network_id: str
    source_tenant_id: str
    source_service_id: str
    status: ListingStatus
    requested_at: datetime
    decided_at: datetime | None
    decided_by_account_ref: str | None
    reason: ListingReason | None

    def __post_init__(self) -> None:
        _record_id(self.id, "id")
        check_network_id(self.network_id, "network_id")
        check_tenant_field(self.source_tenant_id, "source_tenant_id")
        _record_id(self.source_service_id, "source_service_id")
        _enum(self.status, ListingStatus, "status")
        _aware(self.requested_at, "requested_at")
        _optional_aware(self.decided_at, "decided_at")
        _optional_account_ref(self.decided_by_account_ref, "decided_by_account_ref")
        if self.reason is not None:
            _enum(self.reason, ListingReason, "reason")
        _check_listing_status(self)


def _check_listing_status(listing: Listing) -> None:
    status = listing.status
    decided = listing.decided_at is not None
    decider = listing.decided_by_account_ref is not None
    reason = listing.reason is not None
    if status is ListingStatus.PENDING:
        ok = not decided and not decider and not reason
    elif status is ListingStatus.ADMITTED:
        ok = decided and decider and not reason
    elif status in (ListingStatus.DECLINED, ListingStatus.SUSPENDED):
        ok = decided and decider and reason
    else:  # WITHDRAWN: the decider may be the source tenant or the system, so none is allowed.
        ok = decided and not reason
    if not ok:
        raise ValidationFailed("status", MISMATCH_MESSAGE)


# ---------------------------------------------------------------- network lifecycle

_NETWORK_ALLOWED: Final = MappingProxyType(
    {
        NetworkStatus.DRAFT: frozenset({NetworkStatus.ACTIVE}),
        NetworkStatus.ACTIVE: frozenset({NetworkStatus.SUSPENDED, NetworkStatus.CLOSED}),
        NetworkStatus.SUSPENDED: frozenset({NetworkStatus.ACTIVE, NetworkStatus.CLOSED}),
        NetworkStatus.CLOSED: frozenset(),
    }
)


def transition_network(current: NetworkStatus, target: NetworkStatus) -> NetworkStatus:
    _enum(current, NetworkStatus, "current")
    _enum(target, NetworkStatus, "target")
    if target not in _NETWORK_ALLOWED[current]:
        raise InvalidTransition(f"network cannot move from {current.value} to {target.value}")
    return target


def activate_network(network: Network, agreement: Agreement, now: datetime) -> Network:
    """Move to active with the agreement: its reference and version, never its content."""
    _aware(now, "now")
    _record_type(agreement, Agreement, "agreement")
    transition_network(network.status, NetworkStatus.ACTIVE)
    return replace(network, status=NetworkStatus.ACTIVE, agreement=agreement, closed_at=None)


def owner_membership(network: Network, id: str, now: datetime) -> NetworkMembership:
    """The owner organisation's own membership: active, role owner, on the network's agreement.
    The owner is a tenant like any other and may also project (DEC-132 item 2)."""
    _aware(now, "now")
    _record_id(id, "id")
    return NetworkMembership(
        id=id,
        network_id=network.id,
        member_tenant_id=network.owner_tenant_id,
        role=MembershipRole.OWNER,
        status=MembershipStatus.ACTIVE,
        invited_at=network.created_at,
        joined_at=now,
        left_at=None,
        end_reason=None,
        accepted_agreement=network.agreement,
    )


def invite_member(
    network: Network,
    existing_memberships: list[NetworkMembership],
    *,
    id: str,
    tenant_id: str,
    now: datetime,
) -> NetworkMembership:
    """A new invitation. Refused while the tenant has an invited or active row here, and always
    for the owner. A tenant whose only row is left or removed gets a new row; the old row is
    untouched."""
    _aware(now, "now")
    _record_id(id, "id")
    check_tenant_field(tenant_id, "tenant_id")
    if network.status is not NetworkStatus.ACTIVE:
        raise Conflict("the network is not active")
    if tenant_id == network.owner_tenant_id:
        raise Conflict("the tenant is already a member")
    for row in existing_memberships:
        _record_type(row, NetworkMembership, "existing_memberships")
        if row.network_id != network.id:
            raise ValidationFailed("existing_memberships", MISMATCH_MESSAGE)
        if row.member_tenant_id == tenant_id and row.status in (
            MembershipStatus.INVITED,
            MembershipStatus.ACTIVE,
        ):
            raise Conflict("the tenant is already a member")
    return NetworkMembership(
        id=id,
        network_id=network.id,
        member_tenant_id=tenant_id,
        role=MembershipRole.MEMBER,
        status=MembershipStatus.INVITED,
        invited_at=now,
        joined_at=None,
        left_at=None,
        end_reason=None,
        accepted_agreement=None,
    )


def accept_membership(
    network: Network,
    membership: NetworkMembership,
    *,
    agreement: Agreement,
    account_ref: str,
    now: datetime,
) -> NetworkMembership:
    """Invited to active, on the network's current agreement version. The accepting account is
    checked for shape only: the row keeps no field for it."""
    _aware(now, "now")
    _account_ref(account_ref, "account_ref")
    _record_type(agreement, Agreement, "agreement")
    _record_type(membership, NetworkMembership, "membership")
    if membership.network_id != network.id:
        raise ValidationFailed("membership", MISMATCH_MESSAGE)
    if membership.status is not MembershipStatus.INVITED:
        raise InvalidTransition("only an invitation can be accepted")
    if network.status is not NetworkStatus.ACTIVE:
        raise Conflict("the network is not active")
    if network.agreement is None or agreement != network.agreement:
        raise Conflict("the agreement version is not the current one")
    return replace(
        membership,
        status=MembershipStatus.ACTIVE,
        joined_at=now,
        accepted_agreement=agreement,
    )


def end_membership(
    network: Network,
    membership: NetworkMembership,
    *,
    reason: MembershipEndReason,
    now: datetime,
) -> NetworkMembership:
    """Active to left (reason left), or active or invited to removed (reason removed). The join date
    is kept and the leave date is `now`. Ending twice with the same reason returns the row unchanged
    (a retry); a different reason on a closed row is refused."""
    _aware(now, "now")
    _enum(reason, MembershipEndReason, "reason")
    _record_type(membership, NetworkMembership, "membership")
    if membership.network_id != network.id:
        raise ValidationFailed("membership", MISMATCH_MESSAGE)
    if membership.member_tenant_id == network.owner_tenant_id:
        raise NotAllowed("the owner organisation cannot leave its own network")
    if membership.status in (MembershipStatus.LEFT, MembershipStatus.REMOVED):
        if reason is membership.end_reason:
            return membership
        raise InvalidTransition("the membership already ended for another reason")
    if membership.status is MembershipStatus.INVITED and reason is MembershipEndReason.LEFT:
        raise InvalidTransition("an invitation that was never accepted is removed, not left")
    status = (
        MembershipStatus.LEFT if reason is MembershipEndReason.LEFT else MembershipStatus.REMOVED
    )
    return replace(membership, status=status, left_at=now, end_reason=reason)


def was_member_at(membership: NetworkMembership, instant: datetime) -> bool:
    """True from the join instant (inclusive) to the leave instant (exclusive). History queries use
    this; live reads use `status is active`."""
    _aware(instant, "instant")
    if membership.joined_at is None:
        return False
    at = _utc(instant)
    if at < _utc(membership.joined_at):
        return False
    if membership.left_at is None:
        return True
    return at < _utc(membership.left_at)


def is_agreement_behind(network: Network, membership: NetworkMembership) -> bool:
    """True when the network has an agreement and the member's accepted version is missing or lower
    (hazard H-N09)."""
    if network.agreement is None:
        return False
    accepted = membership.accepted_agreement
    return accepted is None or accepted.version < network.agreement.version
