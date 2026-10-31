"""Leave and grant-end semantics in the network scope (TEN-056, DEC-132 items 3 and 6, DEC-542).

When a member leaves, or a grant ends, the registry is already changed (it is the gate, and it is
written first: `membership.py` and `grants.py`). What is left is the network scope: the member's
source for the kind ends and the rows it wrote are marked with the date and the reason
(`ProjectionEndReason`), in one network unit of work. Nothing is deleted, so the history stays
(DEC-132 item 6), and the live reads already leave the rows out because the registry's grants and
memberships no longer allow them (DEC-546).

The end is run by the use case that made the change, and again by the consumer of the governance
event (a lost step is retried by the bus) and by the reconciliation job (`projection_reconcile.py`),
so it is written to be repeated: the registry is asked first and a member that shares the scope
again (a newer grant, a re-joined membership) is left alone, because a handler that runs late must
not end what is now valid; the end is dated by the event (`at`), never by the moment it is handled,
so the source's end date is the date of the decision, which is what a later grant's start is
compared with; a second run changes nothing and writes no audit entry.

A superseded grant is not an end: its successor carries on (the source stays open under it).
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Final

from diucs.application.actor import system_actor
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.network import NetworkRegistry
from diucs.application.ports.outbound.projection import ProjectionEndReason
from diucs.application.ports.outbound.unit_of_work import NetworkUnitOfWorkFactory
from diucs.application.tenancy import bind_network
from diucs.domain.model.network import (
    GrantEndReason,
    GrantScope,
    check_network_id,
    check_tenant_field,
)

AUDIT_ACTION: Final = "U"
USE_CASE: Final = "EndProjection"
CHANNEL: Final = "network-end"


@dataclass(frozen=True, slots=True)
class EndResult:
    sources_ended: int
    rows_marked: int
    skipped: bool = False
    """True when nothing was done because the registry says the member shares again (or the end was
    a supersession): no unit of work was opened."""


class EndProjections:
    def __init__(
        self, uow_factory: NetworkUnitOfWorkFactory, registry: NetworkRegistry, clock: Clock
    ) -> None:
        self._uow_factory = uow_factory
        self._registry = registry
        self._clock = clock

    async def end_grant(
        self,
        network_id: str,
        member_tenant_id: str,
        scope: GrantScope,
        *,
        reason: GrantEndReason,
        at: datetime,
    ) -> EndResult:
        """End the member's source of this kind, unless the member still shares it."""
        check_network_id(network_id)
        check_tenant_field(member_tenant_id, "member_tenant_id")
        if reason is GrantEndReason.SUPERSEDED:
            return EndResult(0, 0, skipped=True)
        if await self._shares(network_id, member_tenant_id, scope):
            return EndResult(0, 0, skipped=True)
        end_reason = (
            ProjectionEndReason.LEFT
            if await self._registry.active_membership(network_id, member_tenant_id) is None
            and reason is GrantEndReason.LAPSED
            else ProjectionEndReason.GRANT_ENDED
        )
        return await self._end(network_id, member_tenant_id, (scope,), end_reason, at)

    async def end_member(
        self, network_id: str, member_tenant_id: str, *, at: datetime
    ) -> EndResult:
        """End every source of the member, with the reason `left`, unless the membership is active
        again."""
        check_network_id(network_id)
        check_tenant_field(member_tenant_id, "member_tenant_id")
        if await self._registry.active_membership(network_id, member_tenant_id) is not None:
            return EndResult(0, 0, skipped=True)
        return await self._end(
            network_id, member_tenant_id, tuple(GrantScope), ProjectionEndReason.LEFT, at
        )

    async def _shares(self, network_id: str, member_tenant_id: str, scope: GrantScope) -> bool:
        now = self._clock.now()
        return any(
            active.network.network.id == network_id
            for active in await self._registry.active_grants_for(member_tenant_id, scope, now)
        )

    async def _end(
        self,
        network_id: str,
        member_tenant_id: str,
        kinds: tuple[GrantScope, ...],
        reason: ProjectionEndReason,
        at: datetime,
    ) -> EndResult:
        ended = 0
        marked = 0
        changed: list[str] = []
        with bind_network(network_id):
            async with self._uow_factory() as uow:
                for kind in kinds:
                    source_ended = await uow.projections.end_source(
                        member_tenant_id, kind, at=at, reason=reason
                    )
                    rows = await uow.projections.mark_ended(
                        member_tenant_id, kind, at=at, reason=reason
                    )
                    ended += int(source_ended)
                    marked += rows
                    if source_ended or rows:
                        changed.append(kind.value)
                if changed:
                    await uow.audit.append(
                        AuditEntry(
                            action=AUDIT_ACTION,
                            use_case=USE_CASE,
                            actor=system_actor(member_tenant_id, CHANNEL),
                            entity_ids=(member_tenant_id,),
                            snapshot={
                                "reason": reason.value,
                                "kinds": sorted(changed),
                                "sources_ended": ended,
                                "rows_marked": marked,
                            },
                            at=at,
                        )
                    )
                await uow.commit()
        return EndResult(ended, marked)
