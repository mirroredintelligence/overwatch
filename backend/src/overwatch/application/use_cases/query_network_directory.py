"""The network directory and criteria, live and as history (TEN-057, DEC-546, DEC-132 item 4).

Same shape as the board: the viewer is checked against the registry, the registry's listings and
grants are read before the unit opens, and a read-only unit in the network scope reads the projected
rows and nothing else. A live row needs an admitted listing and an effective grant of its own scope
(directory for the directory, criteria for the criteria) from a member who is still active. A
departed member's rows, and the rows of a grant that ended, are marked and not deleted
(DEC-542): the history view lists them with the date and the reason, never on the live view.

No entry names the member's tenant, a grant or the member's own service id; the reference of a
row is its listing id.
"""

from dataclasses import dataclass
from datetime import date, datetime

from diucs.application.actor import Actor
from diucs.application.network_access import NetworkAccess, NetworkMemberAccess
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.projection import ProjectionEndReason
from diucs.application.ports.outbound.unit_of_work import NetworkUnitOfWorkFactory
from diucs.application.tenancy import bind_network
from diucs.application.use_cases.query_network_board import NetworkReadUnitNotReadOnly
from diucs.domain.codes import NeedCategory, ServiceCategory
from diucs.domain.model.network import DirectorySource, GrantScope
from diucs.domain.rules.listing import ListingPresentation, listing_presentation
from diucs.domain.rules.projection import LocationProjection, OpeningHourProjection


@dataclass(frozen=True, slots=True)
class NetworkDirectoryEntry:
    row_ref: str
    organisation_name: str
    service_name: str
    category: ServiceCategory
    active: bool
    source: DirectorySource
    contact_label: str | None
    contact_phone: str | None
    location: LocationProjection | None
    opening_hours: tuple[OpeningHourProjection, ...]
    presentation: ListingPresentation
    ended_at: datetime | None
    end_reason: ProjectionEndReason | None


@dataclass(frozen=True, slots=True)
class NetworkDirectoryView:
    entries: tuple[NetworkDirectoryEntry, ...]
    system_name: str
    pathway_name: str
    time_zone: str


@dataclass(frozen=True, slots=True)
class NetworkCriteriaEntry:
    row_ref: str
    organisation_name: str
    service_name: str
    version: int
    age_min: int
    age_max: int | None
    districts: tuple[str, ...]
    accepts: tuple[NeedCategory, ...]
    excludes: tuple[NeedCategory, ...]
    review_by: date
    ended_at: datetime | None
    end_reason: ProjectionEndReason | None


@dataclass(frozen=True, slots=True)
class NetworkCriteriaView:
    entries: tuple[NetworkCriteriaEntry, ...]
    system_name: str
    pathway_name: str
    time_zone: str


def _order(entry: NetworkDirectoryEntry | NetworkCriteriaEntry) -> tuple[str, str, str]:
    return (entry.organisation_name.casefold(), entry.service_name.casefold(), entry.row_ref)


class QueryNetworkDirectory:
    def __init__(
        self, uow_factory: NetworkUnitOfWorkFactory, access: NetworkAccess, clock: Clock
    ) -> None:
        self._uow_factory = uow_factory
        self._access = access
        self._clock = clock

    async def execute(
        self, actor: Actor, network_id: str, *, history: bool = False
    ) -> NetworkDirectoryView:
        member = await self._access.require_member(actor, network_id)
        registry = await self._access.view(member, self._clock.now())
        with bind_network(member.network.id):
            async with self._uow_factory() as uow:
                if not uow.read_only:
                    raise NetworkReadUnitNotReadOnly
                services = await uow.network_view.services(live_only=not history)
        entries: list[NetworkDirectoryEntry] = []
        for row in services:
            service = row.projection
            listed = registry.listing_for(row.source_tenant_id, service.source_service_id)
            if listed is None:
                continue
            presentation = listing_presentation(listed.listing.status)
            if row.ended_at is None:
                if (
                    GrantScope.DIRECTORY not in listed.scopes
                    or presentation is ListingPresentation.HIDDEN
                    or not service.active
                ):
                    continue
            elif not history:
                continue
            entries.append(
                NetworkDirectoryEntry(
                    row_ref=listed.row_ref,
                    organisation_name=listed.organisation_name,
                    service_name=service.service_name,
                    category=service.category,
                    active=service.active,
                    source=service.source,
                    contact_label=service.contact_label,
                    contact_phone=service.contact_phone,
                    location=service.location,
                    opening_hours=service.opening_hours,
                    presentation=presentation,
                    ended_at=row.ended_at,
                    end_reason=row.end_reason,
                )
            )
        entries.sort(key=_order)
        return NetworkDirectoryView(*_labels(entries, member))


def _labels[E: NetworkDirectoryEntry](
    entries: list[E], member: NetworkMemberAccess
) -> tuple[tuple[E, ...], str, str, str]:
    settings = member.settings
    return (tuple(entries), settings.system_name, settings.pathway_name, settings.time_zone)


class QueryNetworkCriteria:
    def __init__(
        self, uow_factory: NetworkUnitOfWorkFactory, access: NetworkAccess, clock: Clock
    ) -> None:
        self._uow_factory = uow_factory
        self._access = access
        self._clock = clock

    async def execute(
        self, actor: Actor, network_id: str, *, history: bool = False
    ) -> NetworkCriteriaView:
        member = await self._access.require_member(actor, network_id)
        registry = await self._access.view(member, self._clock.now())
        with bind_network(member.network.id):
            async with self._uow_factory() as uow:
                if not uow.read_only:
                    raise NetworkReadUnitNotReadOnly
                services = await uow.network_view.services(live_only=not history)
                criteria = await uow.network_view.criteria(live_only=not history)
        name_of = {
            (row.source_tenant_id, row.projection.source_service_id): row.projection.service_name
            for row in services
        }
        entries: list[NetworkCriteriaEntry] = []
        for row in criteria:
            current = row.projection
            key = (row.source_tenant_id, current.source_service_id)
            listed = registry.listing_for(*key)
            name = name_of.get(key)
            if listed is None or name is None:
                continue
            if row.ended_at is None:
                if (
                    GrantScope.CRITERIA not in listed.scopes
                    or listing_presentation(listed.listing.status) is ListingPresentation.HIDDEN
                ):
                    continue
            elif not history:
                continue
            entries.append(
                NetworkCriteriaEntry(
                    row_ref=listed.row_ref,
                    organisation_name=listed.organisation_name,
                    service_name=name,
                    version=current.version,
                    age_min=current.age_min,
                    age_max=current.age_max,
                    districts=current.districts,
                    accepts=current.accepts,
                    excludes=current.excludes,
                    review_by=current.review_by,
                    ended_at=row.ended_at,
                    end_reason=row.end_reason,
                )
            )
        entries.sort(key=_order)
        settings = member.settings
        return NetworkCriteriaView(
            tuple(entries), settings.system_name, settings.pathway_name, settings.time_zone
        )
