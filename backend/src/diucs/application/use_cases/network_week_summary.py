"""The week summary of a network, capacity-derived only (TEN-082, DEC-132 item 4, DEC-136 items 1
and 14, DEC-245 for the tenant's own).

One Monday-to-Sunday week in London time (the network's zone setting allows nothing else yet,
DEC-136 item 13). Read only. The measures come from the network's hourly samples
(`domain/rules/network_sample.py`): the share of services with a current figure, the share of
readings in each status, and the pressure over the week, hour by hour and as hours at each level.
Bookings, cases and outcomes are not shared, so none appears. Small groups are hidden, the whole
week is withheld for a network with fewer than three organisations, and there is no breakdown by
member: a sample holds none, so none can be made.

Roles: the executive and the shift lead, as the tenant's own summary, and only as an active member
of the network (`NetworkAccess.require_member`): another role, a tenant outside the network and an
unknown network are the one refusal.
"""

from dataclasses import dataclass
from datetime import date

from diucs.application.actor import Actor
from diucs.application.network_access import NetworkAccess
from diucs.application.ports.outbound.unit_of_work import NetworkUnitOfWorkFactory
from diucs.application.tenancy import bind_network
from diucs.application.use_cases.query_network_board import NetworkReadUnitNotReadOnly
from diucs.application.use_cases.week_summary import london_week
from diucs.domain.codes import Role
from diucs.domain.errors import NotAllowed, ValidationFailed
from diucs.domain.rules.network_sample import NetworkWeek, week_of_samples

READERS = frozenset({Role.EXEC, Role.LEAD})
READERS_ONLY = "only the exec and the lead may read the network week summary"


@dataclass(frozen=True, slots=True)
class NetworkWeekSummary:
    week_start: date
    week: NetworkWeek
    system_name: str
    pathway_name: str
    time_zone: str


class GetNetworkWeekSummary:
    def __init__(self, uow_factory: NetworkUnitOfWorkFactory, access: NetworkAccess) -> None:
        self._uow_factory = uow_factory
        self._access = access

    async def execute(self, actor: Actor, network_id: str, week_start: date) -> NetworkWeekSummary:
        if actor.role not in READERS:
            raise NotAllowed(READERS_ONLY)
        if week_start.weekday() != 0:
            raise ValidationFailed("week_start", "must be a Monday")
        member = await self._access.require_member(actor, network_id)
        start, end = london_week(week_start)
        with bind_network(member.network.id):
            async with self._uow_factory() as uow:
                if not uow.read_only:
                    raise NetworkReadUnitNotReadOnly
                samples = await uow.network_samples.between(start, end)
        settings = member.settings
        return NetworkWeekSummary(
            week_start=week_start,
            week=week_of_samples(samples, start, end),
            system_name=settings.system_name,
            pathway_name=settings.pathway_name,
            time_zone=settings.time_zone,
        )
