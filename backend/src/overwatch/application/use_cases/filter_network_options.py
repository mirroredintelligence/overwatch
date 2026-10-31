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

One filter, two answers (the merge of WB11, DEC-1176, TEN-051, TEN-053). `execute` is the options
list: the options only, appended after the viewer's own services by the advisor's options screen.
`view` is the same classification with the rows that are not options named as well, for the network
options page and map: "not available on the network. Phone to confirm." for a paused listing,
"criteria not shared. Phone to confirm." for a service whose criteria are not shared (or cannot be
built: fail closed), the reason of a status that cannot take a case, and "outside criteria" with no
case value in it. Nothing of a case is in any reason, in the network scope or in the audit entry,
which holds the listing's opaque reference, the figures and the code of the reason.
"""

import asyncio
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Any, Final

from overwatch.application.actor import Actor
from overwatch.application.network_access import NetworkAccess
from overwatch.application.ports.outbound.audit import AuditEntry
from overwatch.application.ports.outbound.clock import Clock
from overwatch.application.ports.outbound.geo import (
    LatLon,
    PostcodeLocator,
    TravelRange,
    TravelTime,
)
from overwatch.application.ports.outbound.unit_of_work import (
    NetworkUnitOfWorkFactory,
    UnitOfWorkFactory,
)
from overwatch.application.tenancy import bind_network
from overwatch.application.use_cases.filter_options import (
    OUTSIDE_CRITERIA_REASON,
    SHOWN_AS_NOT_SUITABLE,
    SHOWN_AS_OPTION,
    FilterOptionsResult,
    NotSuitable,
    Option,
    criteria_warnings,
    data_age_warnings,
    fits_for,
    option_order_key,
    reason_code,
    status_reason,
    status_warnings,
    travel_legs,
)
from overwatch.application.use_cases.open_case import check_role, missing_fields
from overwatch.application.use_cases.query_network_board import NetworkReadUnitNotReadOnly
from overwatch.domain.codes import AgeBand, CriteriaStatus, NeedCategory, Status
from overwatch.domain.errors import Conflict, NotFound, ValidationFailed
from overwatch.domain.model.criteria import ServiceCriteria
from overwatch.domain.model.network import DirectorySource, GrantScope
from overwatch.domain.model.tenant_policy import DEFAULT_POLICY
from overwatch.domain.rules.criteria_filter import check_hard_criteria
from overwatch.domain.rules.listing import ListingPresentation
from overwatch.domain.rules.london_time import to_london
from overwatch.domain.rules.network_board import (
    NetworkBoardEntry,
    NetworkServiceInput,
    assemble_network_board,
)
from overwatch.domain.rules.projection import CriteriaProjection, ServiceProjection

FILTER_NETWORK_OPTIONS: Final = "FilterNetworkOptions"
READ_ACTION: Final = "R"
PAUSED_REASON: Final = "not available on the network. Phone to confirm."
CRITERIA_NOT_SHARED_REASON: Final = "criteria not shared. Phone to confirm."
SOURCE_TEXT: Final = {
    DirectorySource.MANUAL: "Entered by the organisation",
    DirectorySource.DIRECTORY_OF_SERVICES: "From the Directory of Services",
}

_NETWORK_REASON_CODES: Final[tuple[tuple[str, str], ...]] = (
    (PAUSED_REASON, "paused"),
    (CRITERIA_NOT_SHARED_REASON, "criteria-not-shared"),
)


def network_reason_code(reason: str) -> str:
    """The code of a reason text, for the audit snapshot. The reason of a row may carry an age
    ("not updated for 4 hrs"); the code never does. Any other text is refused."""
    for text, code in _NETWORK_REASON_CODES:
        if reason == text:
            return code
    return reason_code(reason)


@dataclass(frozen=True, slots=True)
class FilterNetworkOptionsCommand:
    actor: Actor
    case_id: str
    network_id: str


@dataclass(frozen=True, slots=True)
class NetworkCaseInputs:
    """What of a case the comparison reads, in memory only: never stored, sent or logged here."""

    age_band: AgeBand
    district: str
    needs: tuple[NeedCategory, ...]


@dataclass(frozen=True, slots=True)
class NetworkOption(Option):
    """An option of another organisation. Facts only: no comment, no pending count, no reporter,
    no tenant, grant or source service id. `service_id` is the listing's opaque reference and
    `organisation` the registry's display name."""

    review_by: date | None = None
    """When the shared criteria are next due for review."""
    contact_label: str | None = None
    """The service line's name, when the organisation shared one."""


@dataclass(frozen=True, slots=True)
class NetworkNotSuitable(NotSuitable):
    organisation: str = ""


@dataclass(frozen=True, slots=True)
class FilterNetworkOptionsResult(FilterOptionsResult):
    system_name: str = ""
    pathway_name: str = ""
    time_zone: str = ""
    """The network's own settings, for the page's header (not a tenant's)."""


@dataclass(frozen=True, slots=True)
class _Candidate:
    option: NetworkOption
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


def classify_network_row(
    entry: NetworkBoardEntry,
    item: NetworkServiceInput,
    projection: CriteriaProjection | None,
    case: NetworkCaseInputs,
    now: datetime,
    today: date,
) -> _Candidate | NetworkNotSuitable | None:
    """One row of the network board: an option, not suitable with the reason, or nothing at all
    (a listing that is hidden, a service that is closed, or a directory or capacity grant that is
    not in force shows nothing, not even a name). Pure.

    A paused listing shows nothing of its figures and nothing else is read of it. A service whose
    criteria are not shared, or cannot be built into a version, cannot be shown to fit: it is not
    suitable (fail closed), never a pass. No reason holds a case value."""

    def not_suitable(reason: str) -> NetworkNotSuitable:
        return NetworkNotSuitable(
            service_id=entry.row_ref,
            name=entry.service_name,
            reason=reason,
            organisation=entry.organisation_name,
        )

    # The order of the board's own rule: a hidden listing shows nothing, a paused one shows its name
    # only, and only then do the grants and the service decide.
    if entry.presentation is ListingPresentation.HIDDEN:
        return None
    if entry.presentation is not ListingPresentation.SHOWN or entry.status is None:
        return not_suitable(PAUSED_REASON)
    shares = item.visible_scopes
    if (
        GrantScope.DIRECTORY not in shares
        or GrantScope.CAPACITY not in shares
        or not item.service.active
    ):
        return None
    data_age = None if entry.reported_at is None else now - entry.reported_at
    reason = status_reason(entry.status, data_age)
    if reason is not None:
        return not_suitable(reason)
    current = None
    if GrantScope.CRITERIA in shares and projection is not None:
        try:
            current = criteria_of(entry.row_ref, projection)
        except ValidationFailed:
            current = None
    if current is None:
        return not_suitable(CRITERIA_NOT_SHARED_REASON)
    verdict = check_hard_criteria(current, case.age_band, case.district, case.needs)
    if not verdict.passes:
        return not_suitable(OUTSIDE_CRITERIA_REASON)
    site = _site(item.service)
    warnings = (
        verdict.warnings
        + status_warnings(entry.status)
        + data_age_warnings(data_age)
        + criteria_warnings(current, today)
    )
    status: Status = entry.status
    return _Candidate(
        option=NetworkOption(
            service_id=entry.row_ref,
            name=entry.service_name,
            status=status,
            effective_available=entry.effective_available,
            over_by=entry.over_by,
            unit_label=entry.unit_label or "",
            data_age=data_age,
            travel=None,
            fits=fits_for(current, case.needs),
            warnings=warnings,
            criteria_id=current.id,
            criteria_version=current.version,
            category=entry.category,
            position=site,
            phone=item.service.contact_phone,
            organisation=entry.organisation_name,
            organisation_source=SOURCE_TEXT[entry.source],
            review_by=current.review_by,
            contact_label=item.service.contact_label,
        ),
        site=site,
    )


def _snapshot_row(
    entry: NetworkBoardEntry, row: _Candidate | NetworkNotSuitable, now: datetime
) -> dict[str, Any]:
    """One row of a display, for the advisor's own audit entry: the listing's opaque reference, the
    status, the figures, the age and the criteria version of an option, and the code of why a row
    was not suitable. No organisation or service name, no tenant or source id."""
    shown: dict[str, Any] = {
        "row_ref": entry.row_ref,
        "status": None if entry.status is None else entry.status.value,
        "number": entry.effective_available,
        "over_by": entry.over_by,
        "data_age_seconds": (
            None if entry.reported_at is None else int((now - entry.reported_at).total_seconds())
        ),
    }
    if isinstance(row, NetworkNotSuitable):
        shown["shown_as"] = SHOWN_AS_NOT_SUITABLE
        shown["reason"] = network_reason_code(row.reason)
    else:
        shown["criteria_version"] = row.option.criteria_version
        shown["shown_as"] = SHOWN_AS_OPTION
    return shown


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

    async def execute(self, command: FilterNetworkOptionsCommand) -> FilterNetworkOptionsResult:
        """The options list: the options only (DEC-1176)."""
        return await self._run(command, with_not_suitable=False)

    async def view(self, command: FilterNetworkOptionsCommand) -> FilterNetworkOptionsResult:
        """The network options page: the options and the rows that are not options, each with its
        reason, and whether no service covers the case's district."""
        return await self._run(command, with_not_suitable=True)

    async def _run(
        self, command: FilterNetworkOptionsCommand, *, with_not_suitable: bool
    ) -> FilterNetworkOptionsResult:
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
            if case.age_band is None or case.postcode is None:  # missing_fields has refused both
                raise ValidationFailed("case", "is incomplete")
            inputs = NetworkCaseInputs(case.age_band, case.postcode, case.needs)
            reference = case.reference

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
        inputs_of: list[NetworkServiceInput] = []
        for row in services:
            if row.source_tenant_id == own:
                continue  # the viewer's own services are the tenant's options, with their actions
            listed = registry.listing_for(row.source_tenant_id, row.projection.source_service_id)
            if listed is None:
                continue
            keys[listed.row_ref] = (row.source_tenant_id, row.projection.source_service_id)
            inputs_of.append(
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
            inputs_of,
            now,
            watch_from=DEFAULT_POLICY.pressure_watch_from,
            high_from=DEFAULT_POLICY.pressure_high_from,
        )
        by_ref = {item.row_ref: item for item in inputs_of}
        today = to_london(now).date()
        patient = self._postcodes.locate(inputs.district)

        candidates: list[_Candidate] = []
        refused: list[NetworkNotSuitable] = []
        shown: list[dict[str, Any]] = []
        for entry in board.entries:
            item = by_ref[entry.row_ref]
            classified = classify_network_row(
                entry,
                item,
                criteria_of_key.get(keys[entry.row_ref]),
                inputs,
                now,
                today,
            )
            if classified is None:
                continue
            if isinstance(classified, NetworkNotSuitable):
                if with_not_suitable:
                    refused.append(classified)
                    shown.append(_snapshot_row(entry, classified, now))
                continue
            candidates.append(classified)
            shown.append(_snapshot_row(entry, classified, now))

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

        out_of_area = False
        if with_not_suitable:
            covered = [
                criteria_of_key[key]
                for ref, key in keys.items()
                if key in criteria_of_key and GrantScope.CRITERIA in by_ref[ref].visible_scopes
            ]
            out_of_area = bool(covered) and all(
                inputs.district not in projection.districts for projection in covered
            )

        refused_in_order = sorted(
            refused,
            key=lambda item: (item.organisation.casefold(), item.name.casefold(), item.service_id),
        )
        return FilterNetworkOptionsResult(
            options=tuple(sorted(options, key=option_order_key)),
            not_suitable=tuple(refused_in_order),
            generated_at=now,
            patient=None if patient is None else patient.lat_lon,
            not_found=patient is None,
            out_of_area=out_of_area,
            system_name=member.settings.system_name,
            pathway_name=member.settings.pathway_name,
            time_zone=member.settings.time_zone,
        )

    async def _travel_range(
        self, patient: LatLon | None, site: LatLon | None
    ) -> TravelRange | None:
        if patient is None or site is None:
            return None
        return await self._travel_time.estimate(patient, site)


def _with_travel(option: NetworkOption, travel: TravelRange | None) -> NetworkOption:
    return replace(option, travel=travel, legs=travel_legs(option.name, travel))
