"""Network listing rules: a member's service offered to the network (TEN-036; DEC-132 item 3,
DEC-136 items 3 and 4, hazard H-N12).

A member registers a listing in its own tenant; the network owner admits, declines, suspends and
reinstates it; the source tenant withdraws its own. A listing shows on the network only when it is
admitted, the member is active, and an effective grant exists for the scope (`visible_scopes`). A
suspended listing stops projecting and reads as unavailable. Pure: no I/O and no clock.
"""

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from diucs.domain.errors import Conflict, InvalidTransition, NotAllowed, ValidationFailed
from diucs.domain.model.network import (
    ACCOUNT_REF_PATTERN,
    RECORD_ID_PATTERN,
    Grant,
    GrantScope,
    Listing,
    ListingReason,
    ListingStatus,
    MembershipStatus,
    NetworkMembership,
    check_network_id,
    check_tenant_field,
)
from diucs.domain.rules.grant import is_effective, may_project

_L = ListingStatus


class ListingPresentation(StrEnum):
    SHOWN = "shown"
    UNAVAILABLE = "unavailable"
    HIDDEN = "hidden"


_ALLOWED: Mapping[ListingStatus, frozenset[ListingStatus]] = MappingProxyType(
    {
        _L.PENDING: frozenset({_L.ADMITTED, _L.DECLINED, _L.WITHDRAWN}),
        _L.ADMITTED: frozenset({_L.SUSPENDED, _L.WITHDRAWN}),
        _L.SUSPENDED: frozenset({_L.ADMITTED, _L.WITHDRAWN}),
        _L.DECLINED: frozenset(),
        _L.WITHDRAWN: frozenset(),
    }
)
# A listing that holds the service: a second request for the same service is refused (H-N12).
_LIVE: Final = frozenset({_L.PENDING, _L.ADMITTED, _L.SUSPENDED})
_PRESENTATION: Final = MappingProxyType(
    {
        _L.ADMITTED: ListingPresentation.SHOWN,
        _L.SUSPENDED: ListingPresentation.UNAVAILABLE,
    }
)
ENUM_MESSAGE: Final = "is not a valid value for this field"
RECORD_MESSAGE: Final = "is not the right kind of record"
AWARE_MESSAGE: Final = "must be a timezone-aware datetime"
ACCOUNT_MESSAGE: Final = "is not a valid account reference"
ID_MESSAGE: Final = "is not a valid id"
REASON_MESSAGE: Final = "needs a listing reason code"


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
        raise ValidationFailed(field, ACCOUNT_MESSAGE)
    return value


def _record_id(value: object, field: str) -> str:
    if type(value) is not str or RECORD_ID_PATTERN.fullmatch(value) is None:
        raise ValidationFailed(field, ID_MESSAGE)
    return value


def _reason(value: object) -> ListingReason:
    if type(value) is not ListingReason:
        raise ValidationFailed("reason", REASON_MESSAGE)
    return value


def transition_listing(current: ListingStatus, target: ListingStatus) -> ListingStatus:
    _checked(current, ListingStatus, "current")
    _checked(target, ListingStatus, "target")
    if target not in _ALLOWED[current]:
        raise InvalidTransition(f"listing cannot move from {current.value} to {target.value}")
    return target


def request_listing(
    existing: Sequence[Listing],
    membership: NetworkMembership,
    *,
    id: str,
    network_id: str,
    source_service_id: str,
    now: datetime,
) -> Listing:
    """A pending listing for the member's own tenant. Refused for an inactive membership, for a
    membership in another network, and while the same service has a live listing."""
    _record_id(id, "id")
    check_network_id(network_id, "network_id")
    _record_id(source_service_id, "source_service_id")
    _record(membership, NetworkMembership, "membership")
    _aware(now, "now")
    if membership.status is not MembershipStatus.ACTIVE:
        raise NotAllowed("only an active member can request a listing")
    if membership.network_id != network_id:
        raise NotAllowed("the membership is not in this network")
    source = membership.member_tenant_id
    for item in existing:
        _record(item, Listing, "existing")
        if (
            item.network_id == network_id
            and item.source_tenant_id == source
            and item.source_service_id == source_service_id
            and item.status in _LIVE
        ):
            raise Conflict("a listing for this service is already open")
    return Listing(
        id=id,
        network_id=network_id,
        source_tenant_id=source,
        source_service_id=source_service_id,
        status=_L.PENDING,
        requested_at=now,
        decided_at=None,
        decided_by_account_ref=None,
        reason=None,
    )


def _owner_decides(
    listing: Listing, *, by_tenant_id: str, owner_tenant_id: str, account_ref: str, now: datetime
) -> None:
    _record(listing, Listing, "listing")
    check_tenant_field(by_tenant_id, "by_tenant_id")
    check_tenant_field(owner_tenant_id, "owner_tenant_id")
    _account(account_ref, "account_ref")
    _aware(now, "now")
    if by_tenant_id != owner_tenant_id:
        raise NotAllowed("only the network owner decides a listing")


def admit_listing(
    listing: Listing, *, by_tenant_id: str, owner_tenant_id: str, account_ref: str, now: datetime
) -> Listing:
    _owner_decides(
        listing,
        by_tenant_id=by_tenant_id,
        owner_tenant_id=owner_tenant_id,
        account_ref=account_ref,
        now=now,
    )
    if listing.status is not _L.PENDING:
        raise InvalidTransition("only a pending listing is admitted; a paused one is reinstated")
    transition_listing(listing.status, _L.ADMITTED)
    return replace(
        listing, status=_L.ADMITTED, decided_at=now, decided_by_account_ref=account_ref, reason=None
    )


def decline_listing(
    listing: Listing,
    *,
    by_tenant_id: str,
    owner_tenant_id: str,
    reason: ListingReason,
    account_ref: str,
    now: datetime,
) -> Listing:
    _owner_decides(
        listing,
        by_tenant_id=by_tenant_id,
        owner_tenant_id=owner_tenant_id,
        account_ref=account_ref,
        now=now,
    )
    _reason(reason)
    transition_listing(listing.status, _L.DECLINED)
    return replace(
        listing,
        status=_L.DECLINED,
        decided_at=now,
        decided_by_account_ref=account_ref,
        reason=reason,
    )


def suspend_listing(
    listing: Listing,
    *,
    by_tenant_id: str,
    owner_tenant_id: str,
    reason: ListingReason,
    account_ref: str,
    now: datetime,
) -> Listing:
    """A suspended listing stops projecting and reads as unavailable (DEC-136 item 3)."""
    _owner_decides(
        listing,
        by_tenant_id=by_tenant_id,
        owner_tenant_id=owner_tenant_id,
        account_ref=account_ref,
        now=now,
    )
    _reason(reason)
    transition_listing(listing.status, _L.SUSPENDED)
    return replace(
        listing,
        status=_L.SUSPENDED,
        decided_at=now,
        decided_by_account_ref=account_ref,
        reason=reason,
    )


def reinstate_listing(
    listing: Listing, *, by_tenant_id: str, owner_tenant_id: str, account_ref: str, now: datetime
) -> Listing:
    _owner_decides(
        listing,
        by_tenant_id=by_tenant_id,
        owner_tenant_id=owner_tenant_id,
        account_ref=account_ref,
        now=now,
    )
    if listing.status is not _L.SUSPENDED:
        raise InvalidTransition("only a suspended listing is reinstated")
    transition_listing(listing.status, _L.ADMITTED)
    return replace(
        listing, status=_L.ADMITTED, decided_at=now, decided_by_account_ref=account_ref, reason=None
    )


def withdraw_listing(
    listing: Listing, *, by_tenant_id: str, account_ref: str | None, now: datetime
) -> Listing:
    """Only the source tenant withdraws its own listing. The decider may be absent: the source
    tenant's own withdrawal is recorded with the time and the account when given."""
    _record(listing, Listing, "listing")
    check_tenant_field(by_tenant_id, "by_tenant_id")
    if account_ref is not None:
        _account(account_ref, "account_ref")
    _aware(now, "now")
    if by_tenant_id != listing.source_tenant_id:
        raise NotAllowed("only the source organisation withdraws its listing")
    transition_listing(listing.status, _L.WITHDRAWN)
    return replace(
        listing,
        status=_L.WITHDRAWN,
        decided_at=now,
        decided_by_account_ref=account_ref,
        reason=None,
    )


def withdraw_for_leave(
    listings: Sequence[Listing], membership: NetworkMembership, *, now: datetime
) -> tuple[Listing, ...]:
    """The withdrawn copies of the member's live listings in its network. Declined listings, other
    members' listings and other networks' listings are left alone."""
    _record(membership, NetworkMembership, "membership")
    _aware(now, "now")
    if membership.status not in (MembershipStatus.LEFT, MembershipStatus.REMOVED):
        raise ValidationFailed("membership", "has not left the network")
    withdrawn: list[Listing] = []
    for listing in listings:
        _record(listing, Listing, "listings")
        if (
            listing.source_tenant_id == membership.member_tenant_id
            and listing.network_id == membership.network_id
            and listing.status in _LIVE
        ):
            transition_listing(listing.status, _L.WITHDRAWN)
            withdrawn.append(
                replace(
                    listing,
                    status=_L.WITHDRAWN,
                    decided_at=now,
                    decided_by_account_ref=None,
                    reason=None,
                )
            )
    return tuple(withdrawn)


def listing_presentation(status: ListingStatus) -> ListingPresentation:
    _checked(status, ListingStatus, "status")
    return _PRESENTATION.get(status, ListingPresentation.HIDDEN)


def visible_scopes(
    listing: Listing, membership: NetworkMembership, grants: Sequence[Grant], now: datetime
) -> frozenset[GrantScope]:
    """The scopes this listing shows on the network: empty unless the listing is admitted and the
    member is active in this network, and then the scopes of its effective grants."""
    _record(listing, Listing, "listing")
    _record(membership, NetworkMembership, "membership")
    _aware(now, "now")
    for grant in grants:
        _record(grant, Grant, "grants")
    if listing.status is not _L.ADMITTED:
        return frozenset()
    if membership.status is not MembershipStatus.ACTIVE:
        return frozenset()
    if membership.member_tenant_id != listing.source_tenant_id:
        return frozenset()
    if membership.network_id != listing.network_id:
        return frozenset()
    return frozenset(
        grant.scope
        for grant in grants
        if grant.grantor_tenant_id == membership.member_tenant_id
        and grant.network_id == membership.network_id
        and is_effective(grant, now)
    )


def shows_on_board(
    listing: Listing, membership: NetworkMembership, grants: Sequence[Grant], now: datetime
) -> bool:
    """A tile needs the directory (its name and hours) and the capacity (its figure). Criteria is
    optional. Nothing here ranks or scores a member."""
    scopes = visible_scopes(listing, membership, grants, now)
    return GrantScope.DIRECTORY in scopes and GrantScope.CAPACITY in scopes


def may_project_listing(
    listing: Listing, membership: NetworkMembership, grant: Grant, now: datetime
) -> bool:
    """A listing projects only while it is admitted, and only through an effective grant of the
    same member (TEN-054's apply step)."""
    _record(listing, Listing, "listing")
    if listing.status is not _L.ADMITTED:
        return False
    if listing.source_tenant_id != membership.member_tenant_id:
        return False
    if listing.network_id != membership.network_id:
        return False
    return may_project(grant, membership, now)
