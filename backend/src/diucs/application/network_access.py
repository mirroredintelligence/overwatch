"""Who may read a network, and what of the registry a network read sees (TEN-057, DEC-546,
DEC-132 item 4).

The membership claim of a token only routes (TEN-059); it is never the authority. Every network read
starts at `NetworkAccess.require_member`, which asks the registry for the viewer's own tenant:

- A role that never sees a network is refused first, with no read at all, so that refusal says
  nothing about any network (`NotAllowed`).
- Everyone else who is not an active member of an active network gets the same `NotFound` from the
  same single read, whether the network is unknown, the tenant never joined, or the tenant left a
  minute ago, so a network id and who belongs to it cannot be discovered. A member sees a network
  that is suspended or closed as not found too.

`NetworkAccess.view` is what the registry says about the listings of a network at one instant: for
each (member, service) the admitted listing, the member's organisation name from the tenant
directory (never from a projection), and the scopes its member's effective grants give
(`visible_scopes`: none unless the listing is admitted and the member is active). A read joins it to
the rows it reads in the network scope. The registry is read before the read-only unit opens, so no
unit of work holds two scopes (DEC-130 item 7).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from diucs.application.actor import Actor
from diucs.application.ports.outbound.network import NetworkRegistry
from diucs.application.ports.outbound.tenants import TenantDirectory
from diucs.domain.codes import Role
from diucs.domain.errors import NotAllowed, NotFound
from diucs.domain.model.network import (
    GrantScope,
    Listing,
    ListingStatus,
    MembershipStatus,
    Network,
    NetworkMembership,
    NetworkStatus,
)
from diucs.domain.model.network_settings import NetworkSettings
from diucs.domain.rules.listing import visible_scopes

NETWORK_NOT_FOUND: Final = "the network was not found"
ROLE_REFUSED: Final = "this role cannot see a network"

# The staff who see the board of their own tenant. Not a reporter, a wall screen (a screen shows a
# network only when its tenant's administrator sets it, TEN-067), an anonymous link, support, audit,
# or an administrator (who runs sharing, not the board).
NETWORK_VIEW_ROLES: Final[frozenset[Role]] = frozenset(
    {Role.ADVISOR, Role.CLINICAL, Role.LEAD, Role.OWNER, Role.EXEC}
)


@dataclass(frozen=True, slots=True)
class NetworkContext:
    """An active network and its settings: what a read needs once the network is known to exist.
    The board projector builds from this, with no viewer (its work is system work)."""

    network: Network
    settings: NetworkSettings


@dataclass(frozen=True, slots=True)
class NetworkMemberAccess(NetworkContext):
    """A viewer the registry has confirmed: an active member of an active network."""

    membership: NetworkMembership


@dataclass(frozen=True, slots=True)
class ListedService:
    """One member's service as the registry lists it. `row_ref` is the listing's own id: opaque, it
    names neither the member nor the service in the member's tenant. `scopes` is empty unless the
    listing is admitted and the member is active."""

    row_ref: str
    organisation_name: str
    listing: Listing
    scopes: frozenset[GrantScope]


@dataclass(frozen=True, slots=True)
class RegistryView:
    listed: Mapping[tuple[str, str], ListedService]

    def listing_for(self, source_tenant_id: str, source_service_id: str) -> ListedService | None:
        return self.listed.get((source_tenant_id, source_service_id))


def _preferred(listings: Sequence[Listing]) -> Listing:
    """An admitted listing wins; among the rest, the latest request."""
    return max(listings, key=lambda x: (x.status is ListingStatus.ADMITTED, x.requested_at))


def _membership_of(rows: Sequence[NetworkMembership]) -> NetworkMembership | None:
    """The active row of a tenant, else its latest (a closed row stays as history)."""
    active = [row for row in rows if row.status is MembershipStatus.ACTIVE]
    if active:
        return active[-1]
    return rows[-1] if rows else None


class NetworkAccess:
    def __init__(self, registry: NetworkRegistry, tenants: TenantDirectory) -> None:
        self._registry = registry
        self._tenants = tenants

    async def require_member(self, actor: Actor, network_id: str) -> NetworkMemberAccess:
        if actor.role not in NETWORK_VIEW_ROLES:
            raise NotAllowed(ROLE_REFUSED)
        membership = await self._registry.active_membership(network_id, actor.tenant_id)
        if membership is None:
            raise NotFound(NETWORK_NOT_FOUND)
        context = await self.open_network(network_id)
        return NetworkMemberAccess(context.network, context.settings, membership)

    async def open_network(self, network_id: str) -> NetworkContext:
        """The network, if it exists and is active, else NotFound. For system work (the board
        projector) and the second step of `require_member`: it checks no viewer."""
        registered = await self._registry.get_network(network_id)
        if registered is None or registered.network.status is not NetworkStatus.ACTIVE:
            raise NotFound(NETWORK_NOT_FOUND)
        return NetworkContext(registered.network, registered.settings)

    async def view(self, access: NetworkContext, now: datetime) -> RegistryView:
        network_id = access.network.id
        listings = await self._registry.listings(network_id)
        grants = await self._registry.grants(network_id)
        memberships = await self._registry.memberships(network_id)
        by_key: dict[tuple[str, str], list[Listing]] = {}
        for listing in listings:
            by_key.setdefault((listing.source_tenant_id, listing.source_service_id), []).append(
                listing
            )
        names: dict[str, str | None] = {}
        listed: dict[tuple[str, str], ListedService] = {}
        for key, group in by_key.items():
            tenant_id = key[0]
            if tenant_id not in names:
                tenant = await self._tenants.get(tenant_id)
                names[tenant_id] = None if tenant is None else tenant.display_name
            name = names[tenant_id]
            if name is None:
                continue
            listing = _preferred(group)
            membership = _membership_of([m for m in memberships if m.member_tenant_id == tenant_id])
            scopes: frozenset[GrantScope] = frozenset()
            if membership is not None:
                scopes = visible_scopes(
                    listing,
                    membership,
                    [g for g in grants if g.grantor_tenant_id == tenant_id],
                    now,
                )
            listed[key] = ListedService(listing.id, name, listing, scopes)
        return RegistryView(listed)
