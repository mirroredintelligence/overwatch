"""The projector's handling of the governance events (TEN-056, DEC-545 item 6, DEC-132 items 3 and
6, DEC-547).

`network.events` carries what the network administration use cases decided (TEN-077, TEN-078), as
the events of the acting tenant. The projector acts on three of them and acknowledges the rest:

- `GrantEffective`: the grantor's projection starts. In the grantor's own tenant scope the
  heartbeat chain is started (`ensure_projection_schedule`) and the producer backfills that kind
  (it is gated by the registry, so a grant that starts in the future projects nothing yet and the
  heartbeat picks it up at its start);
- `GrantEnded`: the source of that member and kind ends in the network scope (`EndProjections`),
  dated by the event; a supersession ends nothing;
- `MemberRemoved`: every source of that member ends there, with the reason `left`.

The message is never the authority. The grant or the network is read from the registry and the
event must agree with it (an event that names another grantor, scope or network is refused); the
sender (the message's verified tenant) must be a party: the grantor or the network owner for a
grant, the member or the owner for a membership. What the registry says now decides what is still
true: `EndProjections` leaves alone a member that shares the scope again. A tenant the directory
does not list as active is skipped (a suspended or offboarded tenant projects nothing). A failure
is raised, so the bus retries it; a refusal is a permanent error for the consumer to dead-letter.
"""

from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Protocol

from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.network import NetworkRegistry
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenancy import bind_tenant
from diucs.application.use_cases.network_leave import EndProjections
from diucs.application.use_cases.project_network import ProjectNetwork
from diucs.application.use_cases.projection_boundaries import ensure_projection_schedule
from diucs.domain.errors import NotAllowed, NotFound
from diucs.domain.events import GrantEffective, GrantEnded, MemberRemoved, from_payload
from diucs.domain.model.network import Grant

GRANT_NOT_FOUND = "the grant was not found"
NETWORK_NOT_FOUND = "the network was not found"
NOT_A_PARTY = "the sender is not a party to this"
DISAGREES = "the event does not match the registry"


class ActiveTenants(Protocol):
    async def active_tenant_ids(self) -> Any: ...


class GovernanceOutcome(StrEnum):
    HANDLED = "handled"
    IGNORED = "ignored"
    SKIPPED = "skipped"


class NetworkGovernance:
    def __init__(
        self,
        registry: NetworkRegistry,
        ends: EndProjections,
        producer: ProjectNetwork,
        uow_factory: UnitOfWorkFactory,
        ids: IdGenerator,
        clock: Clock,
        active_tenants: ActiveTenants,
    ) -> None:
        self._registry = registry
        self._ends = ends
        self._producer = producer
        self._uow_factory = uow_factory
        self._ids = ids
        self._clock = clock
        self._tenants = active_tenants

    async def handle(
        self, event_type: str, payload: Mapping[str, Any], *, bus_tenant: str
    ) -> GovernanceOutcome:
        if event_type not in ("GrantEffective", "GrantEnded", "MemberRemoved"):
            return GovernanceOutcome.IGNORED
        event = from_payload(event_type, payload)
        if isinstance(event, GrantEffective):
            return await self._effective(event, bus_tenant)
        if isinstance(event, GrantEnded):
            return await self._ended(event, bus_tenant)
        if isinstance(event, MemberRemoved):
            return await self._removed(event, bus_tenant)
        return GovernanceOutcome.IGNORED

    async def _grant(self, event: GrantEffective | GrantEnded, bus_tenant: str) -> Grant:
        grant = await self._registry.get_grant(event.grant_id)
        if grant is None:
            raise NotFound(GRANT_NOT_FOUND)
        if (
            grant.network_id != event.network_id
            or grant.grantor_tenant_id != event.grantor_tenant_id
            or grant.scope is not event.scope
        ):
            raise NotAllowed(DISAGREES)
        registered = await self._registry.get_network(grant.network_id)
        if registered is None:
            raise NotFound(NETWORK_NOT_FOUND)
        if bus_tenant not in (grant.grantor_tenant_id, registered.network.owner_tenant_id):
            raise NotAllowed(NOT_A_PARTY)
        return grant

    async def _effective(self, event: GrantEffective, bus_tenant: str) -> GovernanceOutcome:
        grant = await self._grant(event, bus_tenant)
        grantor = grant.grantor_tenant_id
        if grantor not in await self._tenants.active_tenant_ids():
            return GovernanceOutcome.SKIPPED
        with bind_tenant(grantor):
            await ensure_projection_schedule(self._uow_factory, self._ids, self._clock)
            await self._producer.backfill(grant.scope)
        return GovernanceOutcome.HANDLED

    async def _ended(self, event: GrantEnded, bus_tenant: str) -> GovernanceOutcome:
        grant = await self._grant(event, bus_tenant)
        result = await self._ends.end_grant(
            grant.network_id,
            grant.grantor_tenant_id,
            grant.scope,
            reason=event.reason,
            at=event.at,
        )
        return GovernanceOutcome.SKIPPED if result.skipped else GovernanceOutcome.HANDLED

    async def _removed(self, event: MemberRemoved, bus_tenant: str) -> GovernanceOutcome:
        registered = await self._registry.get_network(event.network_id)
        if registered is None:
            raise NotFound(NETWORK_NOT_FOUND)
        if bus_tenant not in (event.member_tenant_id, registered.network.owner_tenant_id):
            raise NotAllowed(NOT_A_PARTY)
        result = await self._ends.end_member(event.network_id, event.member_tenant_id, at=event.at)
        return GovernanceOutcome.SKIPPED if result.skipped else GovernanceOutcome.HANDLED
