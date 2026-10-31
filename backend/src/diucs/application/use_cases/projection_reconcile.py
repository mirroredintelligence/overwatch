"""Reconciling a member's projections with the registry: the revoked-grant leak check (TEN-056,
DEC-132 items 3 and 6, hazard H-N05, audit F section 4.7).

The registry is the truth and the network scope is derived from it, so a lost step (a consumer that
never ran, a commit that failed after the registry was written) is healed here, not hoped away. For
one member of one network the job reads what the network scope holds (the member's sources and any
live row, in a read-only network unit) and ends what the registry no longer allows:

- a member whose membership is not active has every kind ended (reason `left`);
- a kind with a source or a live row and no effective grant of that kind in this network has it
  ended (reason `grant-ended`), which also marks a live row under an ended source (a mark that was
  lost);
- a kind the member still shares is left alone.

The ends are `EndProjections` (its own network unit, opened after the read unit has closed: the two
are never nested), which asks the registry again and writes one audit entry only when something
changed, so a run that finds nothing changes and audits nothing. The heartbeat (`projection_
boundaries.py`) runs this for each network a tenant belongs to or recently left; the use cases that
change the registry run the same end directly, so reconciliation is the safety net and not the path.
"""

from dataclasses import dataclass

from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.network import NetworkRegistry
from diucs.application.ports.outbound.projection import SourceStatus
from diucs.application.ports.outbound.unit_of_work import NetworkUnitOfWorkFactory
from diucs.application.tenancy import bind_network
from diucs.application.use_cases.network_leave import EndProjections
from diucs.domain.model.network import (
    GrantEndReason,
    GrantScope,
    NetworkStatus,
    check_network_id,
    check_tenant_field,
)


class ReconcileUnitNotReadOnly(RuntimeError):
    def __init__(self) -> None:
        super().__init__("the reconciliation reads in a read-only unit of work")


@dataclass(frozen=True, slots=True)
class ReconcileResult:
    checked: int
    """How many kinds of this member had a source or a live row to look at."""
    sources_ended: int
    rows_marked: int


class ReconcileProjection:
    def __init__(
        self,
        reader_factory: NetworkUnitOfWorkFactory,
        ends: EndProjections,
        registry: NetworkRegistry,
        clock: Clock,
    ) -> None:
        self._reader_factory = reader_factory
        self._ends = ends
        self._registry = registry
        self._clock = clock

    async def member(self, network_id: str, member_tenant_id: str) -> ReconcileResult:
        check_network_id(network_id)
        check_tenant_field(member_tenant_id, "member_tenant_id")
        registered = await self._registry.get_network(network_id)
        if registered is None or registered.network.status is not NetworkStatus.ACTIVE:
            return ReconcileResult(0, 0, 0)
        held = await self._held(network_id, member_tenant_id)
        if not held:
            return ReconcileResult(0, 0, 0)
        now = self._clock.now()
        active = await self._registry.active_membership(network_id, member_tenant_id)
        ended = marked = 0
        for kind in sorted(held, key=lambda scope: scope.value):
            if active is None:
                result = await self._ends.end_member(network_id, member_tenant_id, at=now)
            else:
                result = await self._ends.end_grant(
                    network_id, member_tenant_id, kind, reason=GrantEndReason.ENDED, at=now
                )
            ended += result.sources_ended
            marked += result.rows_marked
            if active is None:  # one call ended every kind
                break
        return ReconcileResult(len(held), ended, marked)

    async def _held(self, network_id: str, member_tenant_id: str) -> set[GrantScope]:
        """The kinds the member has a live source or a live row for, read in the network scope."""
        held: set[GrantScope] = set()
        with bind_network(network_id):
            async with self._reader_factory() as uow:
                if not uow.read_only:
                    raise ReconcileUnitNotReadOnly
                for source in await uow.network_view.sources():
                    if (
                        source.source_tenant_id == member_tenant_id
                        and source.status is SourceStatus.ACTIVE
                    ):
                        held.add(source.kind)
                rows = (
                    (GrantScope.DIRECTORY, await uow.network_view.services()),
                    (GrantScope.CAPACITY, await uow.network_view.capacities()),
                    (GrantScope.CRITERIA, await uow.network_view.criteria()),
                )
                for kind, live in rows:
                    if any(row.source_tenant_id == member_tenant_id for row in live):
                        held.add(kind)
        return held
