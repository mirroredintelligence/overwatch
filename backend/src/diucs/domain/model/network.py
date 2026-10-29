"""Network domain model: networks, memberships, grants and listings (TEN-036).

STUB (DEC-010, red commit): the enums and record shapes are final; the rules raise
NotImplementedError until the implementation commit.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from diucs.domain.model.tenant import RESERVED_TENANT_PREFIX

NETWORK_ID_PREFIX: Final = RESERVED_TENANT_PREFIX


class GrantScope(StrEnum):
    CAPACITY = "capacity"
    DIRECTORY = "directory"
    CRITERIA = "criteria"


class GrantPurpose(StrEnum):
    NETWORK_CAPACITY_VIEW = "network-capacity-view"


class GrantStatus(StrEnum):
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
    OUTSIDE_AREA = "outside-area"
    OUTSIDE_PILOT = "outside-pilot"
    DUPLICATE_LISTING = "duplicate-listing"
    DATA_QUALITY = "data-quality"
    SAFETY_CONCERN = "safety-concern"
    AGREEMENT_BREACH = "agreement-breach"
    OTHER = "other"


class DirectorySource(StrEnum):
    MANUAL = "manual"
    DIRECTORY_OF_SERVICES = "directory-of-services"


@dataclass(frozen=True, slots=True)
class Agreement:
    reference: str
    version: int


@dataclass(frozen=True, slots=True)
class Approval:
    account_ref: str
    tenant_id: str
    at: datetime


@dataclass(frozen=True, slots=True)
class Network:
    id: str
    name: str
    owner_tenant_id: str
    status: NetworkStatus
    agreement: Agreement | None
    created_at: datetime
    closed_at: datetime | None


@dataclass(frozen=True, slots=True)
class NetworkMembership:
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


@dataclass(frozen=True, slots=True)
class Grant:
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


@dataclass(frozen=True, slots=True)
class Listing:
    id: str
    network_id: str
    source_tenant_id: str
    source_service_id: str
    status: ListingStatus
    requested_at: datetime
    decided_at: datetime | None
    decided_by_account_ref: str | None
    reason: ListingReason | None


def _todo() -> None:
    raise NotImplementedError


def transition_network(current: NetworkStatus, target: NetworkStatus) -> NetworkStatus:
    _todo()
    return target


def activate_network(network: Network, agreement: Agreement, now: datetime) -> Network:
    _todo()
    return network


def owner_membership(network: Network, id: str, now: datetime) -> NetworkMembership:
    _todo()
    return network  # type: ignore[return-value]


def invite_member(
    network: Network,
    existing_memberships: list[NetworkMembership],
    *,
    id: str,
    tenant_id: str,
    now: datetime,
) -> NetworkMembership:
    _todo()
    return existing_memberships[0]


def accept_membership(
    network: Network,
    membership: NetworkMembership,
    *,
    agreement: Agreement,
    account_ref: str,
    now: datetime,
) -> NetworkMembership:
    _todo()
    return membership


def end_membership(
    network: Network,
    membership: NetworkMembership,
    *,
    reason: MembershipEndReason,
    now: datetime,
) -> NetworkMembership:
    _todo()
    return membership


def was_member_at(membership: NetworkMembership, instant: datetime) -> bool:
    _todo()
    return False


def is_agreement_behind(network: Network, membership: NetworkMembership) -> bool:
    _todo()
    return False


def check_tenant_field(value: object, field: str) -> str:
    _todo()
    return str(value)


def check_network_id(value: object, field: str = "network_id") -> str:
    _todo()
    return str(value)
