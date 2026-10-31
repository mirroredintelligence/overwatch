"""What a member organisation shares with each network, for its administrator (TEN-081, DEC-132
items 3, 4 and 6, DEC-1263).

The tenant administrator sees, for every network its organisation is in: its own membership and the
agreement, what the network holds of the organisation for each kind of sharing (open, or ended with
the date and the reason: states and dates, never a row), and the exact keys that may leave a tenant
for each kind. The keys come from the one allowlist the projection enforces (`body_keys`), so the
screen cannot list a field that does not travel or hide one that does.

The organisation is the token's: the source read names the actor's own tenant and nothing a caller
sent. A member that left is shown its dates and no live state (it has no standing in the network
scope any more); an invitation not yet accepted shows nothing open. A role other than the tenant
administrator is refused before anything is read, in either scope.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

from diucs.application.actor import Actor
from diucs.application.ports.outbound.network import NetworkRegistry
from diucs.application.ports.outbound.projection import ProjectionEndReason, SourceStatus
from diucs.application.ports.outbound.unit_of_work import NetworkUnitOfWorkFactory
from diucs.application.projection import body_keys
from diucs.application.tenancy import bind_network
from diucs.application.use_cases.network_admin import require_role
from diucs.domain.codes import Role
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.network import GrantScope, MembershipStatus, is_agreement_behind
from diucs.domain.rules.projection import PROJECTION_ALLOWLIST_VERSION


@dataclass(frozen=True, slots=True)
class SharedKindView:
    """What the network holds of this organisation for one kind: open, or ended and when and why."""

    kind: GrantScope
    status: SourceStatus
    ended_at: datetime | None
    end_reason: ProjectionEndReason | None


@dataclass(frozen=True, slots=True)
class MemberSharingNetwork:
    network_id: str
    name: str
    membership_id: str
    membership_status: MembershipStatus
    joined_at: datetime | None
    left_at: datetime | None
    agreement_reference: str | None
    agreement_version: int | None
    accepted_agreement_version: int | None
    agreement_behind: bool
    kinds: tuple[SharedKindView, ...]


@dataclass(frozen=True, slots=True)
class MemberSharingView:
    allowlist_version: int
    allowlist: Mapping[GrantScope, tuple[str, ...]]
    networks: tuple[MemberSharingNetwork, ...]


def allowlist_fields() -> Mapping[GrantScope, tuple[str, ...]]:
    """The keys that may leave a tenant, for each kind, sorted: the projection's own list."""
    return MappingProxyType({kind: tuple(sorted(body_keys(kind))) for kind in GrantScope})


class QueryMemberSharing:
    def __init__(
        self, registry: NetworkRegistry, network_reader_factory: NetworkUnitOfWorkFactory
    ) -> None:
        self._registry = registry
        self._reader_factory = network_reader_factory

    async def execute(self, actor: Actor) -> MemberSharingView:
        require_role(actor, Role.TENANT_ADMIN)
        networks: list[MemberSharingNetwork] = []
        for row in await self._registry.memberships_of(actor.tenant_id):
            registered = await self._registry.get_network(row.network_id)
            if registered is None:
                continue
            network = registered.network
            agreement = network.agreement
            accepted = row.accepted_agreement
            live = row.status is MembershipStatus.ACTIVE
            networks.append(
                MemberSharingNetwork(
                    network_id=network.id,
                    name=network.name,
                    membership_id=row.id,
                    membership_status=row.status,
                    joined_at=row.joined_at,
                    left_at=row.left_at,
                    agreement_reference=None if agreement is None else agreement.reference,
                    agreement_version=None if agreement is None else agreement.version,
                    accepted_agreement_version=None if accepted is None else accepted.version,
                    agreement_behind=live and is_agreement_behind(network, row),
                    kinds=await self._kinds(network.id, actor.tenant_id) if live else (),
                )
            )
        return MemberSharingView(
            allowlist_version=PROJECTION_ALLOWLIST_VERSION,
            allowlist=allowlist_fields(),
            networks=tuple(networks),
        )

    async def _kinds(self, network_id: str, tenant_id: str) -> tuple[SharedKindView, ...]:
        found: list[SharedKindView] = []
        with bind_network(network_id):
            async with self._reader_factory() as uow:
                if not uow.read_only:
                    raise ValidationFailed("unit", "must be read-only")
                for kind in GrantScope:
                    state = await uow.network_view.source(tenant_id, kind)
                    if state is not None:
                        found.append(
                            SharedKindView(kind, state.status, state.ended_at, state.end_reason)
                        )
        return tuple(found)


__all__: Sequence[str] = [
    "MemberSharingNetwork",
    "MemberSharingView",
    "QueryMemberSharing",
    "SharedKindView",
    "allowlist_fields",
]
