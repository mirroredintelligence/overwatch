"""Network listing rules (TEN-036). STUB (DEC-010, red commit): every rule raises
NotImplementedError."""

from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum

from diucs.domain.model.network import (
    Grant,
    GrantScope,
    GrantStatus,
    Listing,
    ListingReason,
    ListingStatus,
    NetworkMembership,
)


class ListingPresentation(StrEnum):
    SHOWN = "shown"
    UNAVAILABLE = "unavailable"
    HIDDEN = "hidden"


def _todo() -> None:
    raise NotImplementedError


def transition_listing(current: ListingStatus, target: ListingStatus) -> ListingStatus:
    _todo()
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
    _todo()
    raise NotImplementedError


def admit_listing(
    listing: Listing, *, by_tenant_id: str, owner_tenant_id: str, account_ref: str, now: datetime
) -> Listing:
    _todo()
    return listing


def decline_listing(
    listing: Listing,
    *,
    by_tenant_id: str,
    owner_tenant_id: str,
    reason: ListingReason,
    account_ref: str,
    now: datetime,
) -> Listing:
    _todo()
    return listing


def suspend_listing(
    listing: Listing,
    *,
    by_tenant_id: str,
    owner_tenant_id: str,
    reason: ListingReason,
    account_ref: str,
    now: datetime,
) -> Listing:
    _todo()
    return listing


def reinstate_listing(
    listing: Listing, *, by_tenant_id: str, owner_tenant_id: str, account_ref: str, now: datetime
) -> Listing:
    _todo()
    return listing


def withdraw_listing(
    listing: Listing, *, by_tenant_id: str, account_ref: str | None, now: datetime
) -> Listing:
    _todo()
    return listing


def withdraw_for_leave(
    listings: Sequence[Listing], membership: NetworkMembership, *, now: datetime
) -> tuple[Listing, ...]:
    _todo()
    return tuple(listings)


def listing_presentation(status: ListingStatus) -> ListingPresentation:
    _todo()
    return ListingPresentation.HIDDEN


def visible_scopes(
    listing: Listing, membership: NetworkMembership, grants: Sequence[Grant], now: datetime
) -> frozenset[GrantScope]:
    _todo()
    return frozenset()


def shows_on_board(
    listing: Listing, membership: NetworkMembership, grants: Sequence[Grant], now: datetime
) -> bool:
    _todo()
    return False


def may_project_listing(
    listing: Listing, membership: NetworkMembership, grant: Grant, now: datetime
) -> bool:
    _todo()
    return False


__all__ = ["GrantStatus", "ListingPresentation"]
