"""FilterNetworkOptions: the services of the other organisations of a network that could take a
case, read only (KI-349, KI-181, KI-794, DEC-1176, network-ui.md section 9).

The viewer's own services are the tenant's options (FilterOptions) and carry the booking, phoned
and declined actions. This is the network variant: the rows other organisations share, as the
projections hold them, filtered by the same hard criteria and the same status rules, labelled by
organisation, sorted as the tenant list is (travel low end first, no travel last, then name), never
ranked. A row has no booking, no phoned and no declined action: the only thing to do with it is to
phone the service line.

Four reads, in four units of work, so none holds two scopes (DEC-130 item 7): the case in the
tenant's unit, the registry, the projected rows in a read-only unit in the network scope, and the
tenant's audit entry of what was shown. No case value reaches the network scope: the case is read
first, closed, and the network read takes no parameter from it. A row is an option only when the
organisation shares its directory, capacity and criteria (a service whose criteria are not shared
cannot be filtered, so it is not offered: fail closed), its status can take a case, and its current
criteria cover the case. The row is named by its listing id, never by a tenant or a service id of
the member; the organisation's name comes from the registry.
"""

import asyncio
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Final

from diucs.application.actor import Actor
from diucs.application.network_access import NetworkAccess
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.geo import LatLon, PostcodeLocator, TravelRange, TravelTime
from diucs.application.ports.outbound.unit_of_work import (
    NetworkUnitOfWorkFactory,
    UnitOfWorkFactory,
)
from diucs.application.tenancy import bind_network
from diucs.application.use_cases.filter_options import (
    FilterOptionsResult,
    Option,
    criteria_warnings,
    data_age_warnings,
    fits_for,
    option_order_key,
    status_reason,
    status_warnings,
    travel_legs,
)
from diucs.application.use_cases.open_case import check_role, missing_fields
from diucs.application.use_cases.query_network_board import NetworkReadUnitNotReadOnly
from diucs.domain.codes import CriteriaStatus, Status
from diucs.domain.errors import Conflict, NotFound, ValidationFailed
from diucs.domain.model.criteria import ServiceCriteria
from diucs.domain.model.network import DirectorySource, GrantScope
from diucs.domain.model.tenant_policy import DEFAULT_POLICY
from diucs.domain.rules.criteria_filter import check_hard_criteria
from diucs.domain.rules.listing import ListingPresentation, listing_presentation
from diucs.domain.rules.london_time import to_london
from diucs.domain.rules.network_board import (
    NetworkBoardEntry,
    NetworkServiceInput,
    assemble_network_board,
)
from diucs.domain.rules.projection import CriteriaProjection, ServiceProjection

FILTER_NETWORK_OPTIONS: Final = "FilterNetworkOptions"
READ_ACTION: Final = "R"
SOURCE_TEXT: Final = {
    DirectorySource.MANUAL: "Entered by the organisation",
    DirectorySource.DIRECTORY_OF_SERVICES: "From the Directory of Services",
}


@dataclass(frozen=True, slots=True)
class FilterNetworkOptionsCommand:
    actor: Actor
    case_id: str
    network_id: str


@dataclass(frozen=True, slots=True)
class _Candidate:
    option: Option
    site: LatLon | None


def criteria_of(row_ref: str, projection: CriteriaProjection) -> ServiceCriteria:
    """A projected criteria version as the filter reads it. Current by construction (only a current
    version is projected, DEC-132); named by the listing, never by the member's own ids."""
    return ServiceCriteria(
        id=f"{row_ref}-v{projection.version}",
        service_id=row_ref,
        version=projection.version,
        status=CriteriaStatus.CURRENT,
        age_min=projection.age_min,
        age_max=projection.age_max,
        districts=frozenset(projection.districts),
        accepts=frozenset(projection.accepts),
        excludes=frozenset(projection.excludes),
        review_by=projection.review_by,
        owner_role_id="network",
    )


def _site(service: ServiceProjection) -> LatLon | None:
    location = service.location
    if location is None or location.latitude is None or location.longitude is None:
        return None
    return LatLon(lat=location.latitude, lon=location.longitude)


class FilterNetworkOptions:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        network_uow_factory: NetworkUnitOfWorkFactory,
        access: NetworkAccess,
        clock: Clock,
        postcodes: PostcodeLocator,
        travel_time: TravelTime,
    ) -> None:
        self._uow_factory = uow_factory
        self._network_uow_factory = network_uow_factory
        self._access = access
        self._clock = clock
        self._postcodes = postcodes
        self._travel_time = travel_time

    async def execute(self, command: FilterNetworkOptionsCommand) -> FilterOptionsResult:
        check_role(command.actor)
        # Not a member, a network that is closed or unknown, and a role that never sees a network
        # are refused here before the case is read (the one NotFound of NetworkAccess).
        member = await self._access.require_member(command.actor, command.network_id)

        async with self._uow_factory() as uow:
            case = await uow.cases.get(command.case_id)
            if case is None:
                raise NotFound("no case with this id")
            if case.closed_at is not None:
                raise Conflict("the case is closed and cannot be filtered")
            missing = missing_fields(case)
            if missing:
                raise ValidationFailed(
                    ", ".join(missing), "a case needs these before options can be filtered"
                )
            age_band, district, needs = case.age_band, case.postcode, case.needs
            reference = case.reference
            if age_band is None or district is None:  # missing_fields has refused both
                raise ValidationFailed("case", "is incomplete")

        now = self._clock.now()
        registry = await self._access.view(member, now)
        with bind_network(member.network.id):
            async with self._network_uow_factory() as network:
                if not network.read_only:
                    raise NetworkReadUnitNotReadOnly
                services = await network.network_view.services()
                capacities = await network.network_view.capacities()
                criteria_rows = await network.network_view.criteria()
        capacity_of = {
            (row.source_tenant_id, row.projection.source_service_id): row.projection
            for row in capacities
        }
        criteria_of_key = {
            (row.source_tenant_id, row.projection.source_service_id): row.projection
            for row in criteria_rows
        }
        own = command.actor.tenant_id
        keys: dict[str, tuple[str, str]] = {}
        inputs: list[NetworkServiceInput] = []
        for row in services:
            if row.source_tenant_id == own:
                continue  # the viewer's own services are the tenant's options, with their actions
            listed = registry.listing_for(row.source_tenant_id, row.projection.source_service_id)
            if listed is None:
                continue
            keys[listed.row_ref] = (row.source_tenant_id, row.projection.source_service_id)
            inputs.append(
                NetworkServiceInput(
                    row_ref=listed.row_ref,
                    organisation_name=listed.organisation_name,
                    service=row.projection,
                    capacity=capacity_of.get(
                        (row.source_tenant_id, row.projection.source_service_id)
                    ),
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
        by_ref = {item.row_ref: item for item in inputs}
        today = to_london(now).date()
        patient = self._postcodes.locate(district)

        candidates: list[_Candidate] = []
        shown: list[dict[str, Any]] = []
        for entry in board.entries:
            item = by_ref[entry.row_ref]
            criteria_projection = criteria_of_key.get(keys[entry.row_ref])
            candidate = self._candidate(
                entry, item, criteria_projection, age_band, district, needs, today, now
            )
            if candidate is None:
                continue
            candidates.append(candidate)
            shown.append(
                {
                    "row_ref": entry.row_ref,
                    "status": None if entry.status is None else entry.status.value,
                    "number": entry.effective_available,
                    "over_by": entry.over_by,
                    "data_age_seconds": (
                        None
                        if entry.reported_at is None
                        else int((now - entry.reported_at).total_seconds())
                    ),
                    "criteria_version": candidate.option.criteria_version,
                    "shown_as": "option",
                }
            )

        # No unit is open: the travel estimates are awaited here, all at once.
        ranges = await asyncio.gather(
            *(self._travel_range(patient.lat_lon if patient else None, c.site) for c in candidates)
        )
        options = [
            _with_travel(candidate.option, travel)
            for candidate, travel in zip(candidates, ranges, strict=True)
        ]

        async with self._uow_factory() as uow:
            await uow.audit.append(
                AuditEntry(
                    action=READ_ACTION,
                    use_case=FILTER_NETWORK_OPTIONS,
                    actor=command.actor,
                    entity_ids=(command.case_id,),
                    snapshot={"reference": reference, "services": shown},
                    at=now,
                )
            )
            await uow.commit()

        return FilterOptionsResult(
            options=tuple(sorted(options, key=option_order_key)),
            not_suitable=(),
            generated_at=now,
            patient=None if patient is None else patient.lat_lon,
            not_found=patient is None,
        )

    def _candidate(
        self,
        entry: NetworkBoardEntry,
        item: NetworkServiceInput,
        projection: CriteriaProjection | None,
        age_band: Any,
        district: str,
        needs: Any,
        today: Any,
        now: datetime,
    ) -> _Candidate | None:
        shares = item.visible_scopes
        if (
            GrantScope.DIRECTORY not in shares
            or GrantScope.CAPACITY not in shares
            or GrantScope.CRITERIA not in shares
            or listing_presentation(item.listing) is ListingPresentation.HIDDEN
            or not item.service.active
            or entry.status is None
            or projection is None
        ):
            return None
        data_age = None if entry.reported_at is None else now - entry.reported_at
        if status_reason(entry.status, data_age) is not None:
            return None
        current = criteria_of(entry.row_ref, projection)
        verdict = check_hard_criteria(current, age_band, district, needs)
        if not verdict.passes:
            return None
        site = _site(item.service)
        warnings = (
            verdict.warnings
            + status_warnings(entry.status)
            + data_age_warnings(data_age)
            + criteria_warnings(current, today)
        )
        status: Status = entry.status
        return _Candidate(
            option=Option(
                service_id=entry.row_ref,
                name=entry.service_name,
                status=status,
                effective_available=entry.effective_available,
                over_by=entry.over_by,
                unit_label=entry.unit_label or "",
                data_age=data_age,
                travel=None,
                fits=fits_for(current, needs),
                warnings=warnings,
                criteria_id=current.id,
                criteria_version=current.version,
                category=entry.category,
                position=site,
                phone=item.service.contact_phone,
                organisation=entry.organisation_name,
                organisation_source=SOURCE_TEXT[entry.source],
            ),
            site=site,
        )

    async def _travel_range(
        self, patient: LatLon | None, site: LatLon | None
    ) -> TravelRange | None:
        if patient is None or site is None:
            return None
        return await self._travel_time.estimate(patient, site)


def _with_travel(option: Option, travel: TravelRange | None) -> Option:
    return replace(option, travel=travel, legs=travel_legs(option.name, travel))
