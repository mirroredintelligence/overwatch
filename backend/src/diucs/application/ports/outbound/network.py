"""Outbound port: the network registry (TEN-051, DEC-541, DEC-132, DEC-134 item 9).

The registry is the platform's record of its networks: the `Network`, `NetworkMembership`, `Grant`
and `Listing` nodes, which carry no `tenantId`. It is global: it runs before and outside any scope,
it is not part of a unit of work, and it never holds capacity, a person or a message.

Every method that reads takes ids of the right kind (a tenant id in a tenant place, a network id in
a network place) and answers `None` or an empty list, sending nothing, for an id of another shape.
Every method that writes is a guarded create or a compare-and-set on the status it expects, and
raises `Conflict` when the row is not as expected (a lost race, a key taken, a live row already
there). A record the domain refuses is `NetworkRecordInvalid`: a configuration fault, fail closed.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from diucs.domain.model.network import (
    Grant,
    GrantScope,
    GrantStatus,
    Listing,
    ListingStatus,
    MembershipStatus,
    Network,
    NetworkMembership,
    NetworkStatus,
)
from diucs.domain.model.network_settings import NetworkSettings


class NetworkRecordInvalid(RuntimeError):
    """A record in the network registry is not one the domain accepts. A configuration fault:
    callers fail closed. The text is fixed and holds no value."""


@dataclass(frozen=True, slots=True)
class RegisteredNetwork:
    """A network and its settings, as the registry holds them."""

    network: Network
    settings: NetworkSettings


@dataclass(frozen=True, slots=True)
class ActiveGrant:
    """A grant that may project now (`may_project`), with its network and the grantor's active
    membership: what the projector's gate hands on."""

    network: RegisteredNetwork
    grant: Grant
    membership: NetworkMembership


class NetworkRegistry(Protocol):
    async def get_network(self, network_id: str) -> RegisteredNetwork | None: ...

    async def memberships(self, network_id: str) -> Sequence[NetworkMembership]:
        """Every row of the network, oldest first (a closed row is history and stays)."""
        ...

    async def memberships_of(self, tenant_id: str) -> Sequence[NetworkMembership]:
        """Every row of this tenant in every network, by network and then oldest first."""
        ...

    async def active_membership(self, network_id: str, tenant_id: str) -> NetworkMembership | None:
        """The tenant's active row in this network, or None: the membership check of every
        network read (a member who left is refused at once)."""
        ...

    async def get_grant(self, grant_id: str) -> Grant | None: ...

    async def grants(self, network_id: str) -> Sequence[Grant]: ...

    async def grants_of(self, tenant_id: str) -> Sequence[Grant]:
        """The grants this tenant has given, in every network."""
        ...

    async def active_grants_for(
        self, tenant_id: str, scope: GrantScope, now: datetime
    ) -> Sequence[ActiveGrant]:
        """The projector's gate: the grants of this grantor and scope that are effective at `now`
        (`may_project`) in an active network where the grantor is an active member."""
        ...

    async def get_listing(self, listing_id: str) -> Listing | None: ...

    async def listings(self, network_id: str) -> Sequence[Listing]: ...

    async def listings_of(self, network_id: str, tenant_id: str) -> Sequence[Listing]: ...

    async def create_network(self, network: Network, settings: NetworkSettings) -> None: ...

    async def save_network(
        self, network: Network, settings: NetworkSettings, *, expected_status: NetworkStatus
    ) -> None: ...

    async def create_membership(self, membership: NetworkMembership) -> None:
        """Conflict when the tenant already has an invited or active row in this network."""
        ...

    async def save_membership(
        self, membership: NetworkMembership, *, expected_status: MembershipStatus
    ) -> None: ...

    async def create_grant(self, grant: Grant) -> None: ...

    async def save_grant(self, grant: Grant, *, expected_status: GrantStatus) -> None: ...

    async def create_listing(self, listing: Listing) -> None:
        """Conflict when the service already has a live listing in this network (hazard H-N12)."""
        ...

    async def save_listing(self, listing: Listing, *, expected_status: ListingStatus) -> None: ...
