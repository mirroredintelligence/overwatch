"""The network board (TEN-057, DEC-546, DEC-132 item 4, DEC-134 items 6 and 8).

Read-only. The viewer is checked against the registry first (`NetworkAccess`: role, then an active
membership of an active network, else NotFound). The registry's listings and grants are read before
the unit opens; then a read-only unit of work in the network scope reads the projected services and
capacity inputs, and nothing else, so no unit holds two scopes and the read cannot write.

A projection holds the inputs of a status and never the status, so each row's status is worked out
here, at the time of the read, by the tenant board's own rule (`assemble_network_board`): a service
that stops reporting reads Not updated with no new event, and a row's age is from the source's
report time, not from when it was projected (hazard H-N07). A row with no admitted listing, no
effective capacity and directory grant, or a member who has left is not on the board (it is in the
history, `QueryNetworkDirectory`). Pressure is over the shown rows, with the platform's default
thresholds (a per-network policy is a later decision). The network's name labels and time zone
travel with the result; no row names the member's tenant, a grant or the member's own service id.
"""

from dataclasses import dataclass

from diucs.application.actor import Actor
from diucs.application.network_access import NetworkAccess, NetworkContext
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.unit_of_work import NetworkUnitOfWorkFactory
from diucs.application.tenancy import bind_network
from diucs.domain.model.tenant_policy import DEFAULT_POLICY
from diucs.domain.rules.network_board import (
    NetworkBoard,
    NetworkServiceInput,
    assemble_network_board,
)


class NetworkReadUnitNotReadOnly(RuntimeError):
    def __init__(self) -> None:
        super().__init__("a network read needs a read-only unit of work")


@dataclass(frozen=True, slots=True)
class NetworkBoardView:
    board: NetworkBoard
    system_name: str
    pathway_name: str
    time_zone: str


class QueryNetworkBoard:
    def __init__(
        self, uow_factory: NetworkUnitOfWorkFactory, access: NetworkAccess, clock: Clock
    ) -> None:
        self._uow_factory = uow_factory
        self._access = access
        self._clock = clock

    async def execute(self, actor: Actor, network_id: str) -> NetworkBoardView:
        member = await self._access.require_member(actor, network_id)
        return await self._board(member)

    async def build(self, network_id: str) -> NetworkBoardView:
        """The board of a network for system work (the projector's rebuild): no viewer, so no
        membership check, but the network must exist and be active (NotFound otherwise). Never
        reached from a request: a request goes through `execute`."""
        return await self._board(await self._access.open_network(network_id))

    async def _board(self, member: NetworkContext) -> NetworkBoardView:
        now = self._clock.now()
        registry = await self._access.view(member, now)
        with bind_network(member.network.id):
            async with self._uow_factory() as uow:
                if not uow.read_only:
                    raise NetworkReadUnitNotReadOnly
                services = await uow.network_view.services()
                capacities = await uow.network_view.capacities()
        capacity_of = {
            (row.source_tenant_id, row.projection.source_service_id): row.projection
            for row in capacities
        }
        inputs: list[NetworkServiceInput] = []
        for row in services:
            service = row.projection
            listed = registry.listing_for(row.source_tenant_id, service.source_service_id)
            if listed is None:
                continue
            inputs.append(
                NetworkServiceInput(
                    row_ref=listed.row_ref,
                    organisation_name=listed.organisation_name,
                    service=service,
                    capacity=capacity_of.get((row.source_tenant_id, service.source_service_id)),
                    listing=listed.listing.status,
                    visible_scopes=listed.scopes,
                )
            )
        board = assemble_network_board(
            inputs,
            now,
            watch_from=DEFAULT_POLICY.pressure_watch_from,
            high_from=DEFAULT_POLICY.pressure_high_from,
        )
        settings = member.settings
        return NetworkBoardView(
            board, settings.system_name, settings.pathway_name, settings.time_zone
        )
