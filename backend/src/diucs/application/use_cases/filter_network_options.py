"""FilterNetworkOptions: the services of OTHER organisations in a network that may take a case, and
why the others may not (WB11, TEN-051, TEN-053, DEC-136 item 1, DEC-134 item 8). The network
variant of FilterOptions (U12).

Read-only, capacity-derived, never a way to book. An advisor is in a call about a case that
belongs to their own organisation. This gives them, from what the other organisations of their
network share (capacity, the directory and the criteria, through grants and admitted listings),
the services that meet the case's hard criteria, with the status at the time of the read, how old
the figure is, the travel time and the service line, so the advisor can phone the service. Nothing
is requested from it, nothing is written in it, and nothing it holds can be turned into a booking:
a booking carries an age band and a need, which is patient-level data that stays in one
organisation (DEC-136 item 1).

How the privacy holds. Three scopes are involved and no unit of work holds two of them (DEC-130
item 7): the registry (who is a member, which listings are admitted, which scopes each member
shares), the network scope (the projected rows, read by the three existing network reads), and the
advisor's own tenant (the case). The network is read first, with no word of the case in any read.
The case's age band, district and needs are then read in the advisor's tenant and compared, in
memory and by the same rule the tenant list uses (`check_hard_criteria`), with the shared criteria
rows. Nothing of the case is passed to a network read, to a message or to a log. The only thing
written is the advisor's own tenant's audit entry of what they were shown (DEC-035, DEC-042),
which holds opaque row references and figures and no organisation, tenant or service id of another
organisation.

Own organisation. The advisor's own services are in their own list; the rows of the advisor's own
organisation are left out here, so the two lists never repeat each other (DEC-136 item 1).

Fail closed. A service whose criteria were not shared cannot be checked, so it is not suitable; a
criteria row that cannot be built is the same; a paused listing is shown as not available on the
network, with nothing else read of it.
"""

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Any, Final

from diucs.application.actor import Actor
from diucs.application.network_access import NetworkAccess
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.geo import LatLon, PostcodeLocator, TravelRange, TravelTime
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.filter_options import (
    OUTSIDE_CRITERIA_REASON,
    SHOWN_AS_NOT_SUITABLE,
    SHOWN_AS_OPTION,
    criteria_warnings,
    data_age_warnings,
    fits_for,
    reason_code,
    status_reason,
    status_warnings,
)
from diucs.application.use_cases.network_board_projector import NetworkBoardProjector
from diucs.application.use_cases.open_case import check_role, missing_fields
from diucs.application.use_cases.query_network_directory import (
    NetworkCriteriaEntry,
    NetworkDirectoryEntry,
    QueryNetworkCriteria,
    QueryNetworkDirectory,
)
from diucs.domain.codes import AgeBand, CriteriaStatus, NeedCategory, ServiceCategory, Status
from diucs.domain.errors import Conflict, NotFound, ValidationFailed
from diucs.domain.model.criteria import ServiceCriteria
from diucs.domain.rules.criteria_filter import check_hard_criteria
from diucs.domain.rules.listing import ListingPresentation
from diucs.domain.rules.london_time import to_london
from diucs.domain.rules.network_board import NetworkBoardEntry

FILTER_NETWORK_OPTIONS: Final = "FilterNetworkOptions"
READ_ACTION: Final = "R"
PAUSED_REASON: Final = "not available on the network. Phone to confirm."
CRITERIA_NOT_SHARED_REASON: Final = "criteria not shared. Phone to confirm."

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
class NetworkCaseInputs:
    """What of a case the comparison reads, in memory only: never stored, sent or logged here."""

    age_band: AgeBand
    district: str
    needs: tuple[NeedCategory, ...]


@dataclass(frozen=True, slots=True)
class FilterNetworkOptionsCommand:
    actor: Actor
    network_id: str
    case_id: str


@dataclass(frozen=True, slots=True)
class NetworkOption:
    """A service of another organisation that may take the case. Facts only: no comment, no pending
    count, no reporter, no tenant or service id of the organisation. `row_ref` is the listing's own
    opaque reference."""

    row_ref: str
    organisation_name: str
    service_name: str
    category: ServiceCategory
    status: Status
    effective_available: int | None
    over_by: int | None
    unit_label: str
    data_age: timedelta | None
    fits: tuple[str, ...]
    warnings: tuple[str, ...]
    criteria_version: int
    review_by: date
    contact_label: str | None
    contact_phone: str | None
    position: LatLon | None
    travel: TravelRange | None = None


@dataclass(frozen=True, slots=True)
class NetworkNotSuitable:
    row_ref: str
    organisation_name: str
    service_name: str
    reason: str


@dataclass(frozen=True, slots=True)
class FilterNetworkOptionsResult:
    options: tuple[NetworkOption, ...]
    not_suitable: tuple[NetworkNotSuitable, ...]
    generated_at: datetime
    system_name: str
    pathway_name: str
    time_zone: str
    patient: LatLon | None = None
    """The centre of the case's postcode district, for the map and the travel time. It is the
    advisor's own case's district and it goes back to the advisor only."""
    not_found: bool = False
    """The locator does not know the case's district."""
    out_of_area: bool = False
    """No service of the network covers the case's district."""


def _service_criteria(entry: NetworkCriteriaEntry) -> ServiceCriteria | None:
    """The shared criteria as the version the rule reads, or None when they cannot be one."""
    try:
        return ServiceCriteria(
            id=entry.row_ref,
            service_id=entry.row_ref,
            version=entry.version,
            status=CriteriaStatus.CURRENT,
            age_min=entry.age_min,
            age_max=entry.age_max,
            districts=frozenset(entry.districts),
            accepts=frozenset(entry.accepts),
            excludes=frozenset(entry.excludes),
            review_by=entry.review_by,
            owner_role_id="network",
        )
    except ValidationFailed:
        return None


def classify_network_row(
    entry: NetworkBoardEntry,
    criteria: NetworkCriteriaEntry | None,
    where: NetworkDirectoryEntry | None,
    case: NetworkCaseInputs,
    now: datetime,
    today: date,
) -> NetworkOption | NetworkNotSuitable:
    """One row of the network: an option or not suitable, with the reason. Pure."""

    def not_suitable(reason: str) -> NetworkNotSuitable:
        return NetworkNotSuitable(
            entry.row_ref, entry.organisation_name, entry.service_name, reason
        )

    # A paused listing shows nothing of its figures: nothing else about it is read.
    if entry.presentation is not ListingPresentation.SHOWN or entry.status is None:
        return not_suitable(PAUSED_REASON)
    data_age = None if entry.reported_at is None else now - entry.reported_at
    reason = status_reason(entry.status, data_age)
    if reason is not None:
        return not_suitable(reason)
    shared = None if criteria is None else _service_criteria(criteria)
    if shared is None:
        # Fail closed: criteria that are not shared (or cannot be read) cannot show the case fits.
        return not_suitable(CRITERIA_NOT_SHARED_REASON)
    result = check_hard_criteria(shared, case.age_band, case.district, case.needs)
    if not result.passes:
        return not_suitable(OUTSIDE_CRITERIA_REASON)

    position = None
    location = None if where is None else where.location
    if location is not None and location.latitude is not None and location.longitude is not None:
        position = LatLon(location.latitude, location.longitude)
    return NetworkOption(
        row_ref=entry.row_ref,
        organisation_name=entry.organisation_name,
        service_name=entry.service_name,
        category=entry.category,
        status=entry.status,
        effective_available=entry.effective_available,
        over_by=entry.over_by,
        unit_label=entry.unit_label or "Phone to confirm",
        data_age=data_age,
        fits=fits_for(shared, case.needs),
        warnings=(
            result.warnings
            + status_warnings(entry.status)
            + data_age_warnings(data_age)
            + criteria_warnings(shared, today)
        ),
        criteria_version=shared.version,
        review_by=shared.review_by,
        contact_label=None if where is None else where.contact_label,
        contact_phone=None if where is None else where.contact_phone,
        position=position,
    )


def option_order_key(option: NetworkOption) -> tuple[int, int, str, str, str]:
    """Travel low end first; no travel after every option with travel; then organisation, service
    and reference. An order, never a rank."""
    organisation = option.organisation_name.casefold()
    service = option.service_name.casefold()
    if option.travel is None:
        return (1, 0, organisation, service, option.row_ref)
    return (0, option.travel.low_minutes, organisation, service, option.row_ref)


def _snapshot_row(
    entry: NetworkBoardEntry,
    row: NetworkOption | NetworkNotSuitable,
    now: datetime,
) -> dict[str, Any]:
    """One row of a display, for the advisor's own audit entry: opaque reference, status, figures,
    age and criteria version, and the code of why it was not suitable. No organisation or service
    name, no tenant or source id."""
    data_age = None if entry.reported_at is None else now - entry.reported_at
    number = entry.effective_available if entry.effective_available is not None else entry.used
    shown: dict[str, Any] = {
        "ref": entry.row_ref,
        "status": None if entry.status is None else entry.status.value,
        "number": number,
        "data_age_seconds": None if data_age is None else int(data_age.total_seconds()),
        "over_by": entry.over_by,
    }
    if isinstance(row, NetworkOption):
        shown["shown_as"] = SHOWN_AS_OPTION
        shown["criteria_version"] = row.criteria_version
    else:
        shown["shown_as"] = SHOWN_AS_NOT_SUITABLE
        shown["reason"] = network_reason_code(row.reason)
    return shown


class FilterNetworkOptions:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        access: NetworkAccess,
        projector: NetworkBoardProjector,
        directory: QueryNetworkDirectory,
        criteria: QueryNetworkCriteria,
        postcodes: PostcodeLocator,
        travel_time: TravelTime,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._access = access
        self._projector = projector
        self._directory = directory
        self._criteria = criteria
        self._postcodes = postcodes
        self._travel_time = travel_time

    async def execute(self, command: FilterNetworkOptionsCommand) -> FilterNetworkOptionsResult:
        actor = command.actor
        check_role(actor)
        # Who may read this network, from the registry (a non-member, a member who left and an
        # unknown network are the one NotFound), and which listings are the advisor's own.
        member = await self._access.require_member(actor, command.network_id)
        now = self._clock.now()
        registry = await self._access.view(member, now)
        own_refs = {
            listed.row_ref
            for listed in registry.listed.values()
            if listed.listing.source_tenant_id == actor.tenant_id
        }
        # The network, each read in its own unit in the network scope, with no word of the case.
        board = (await self._projector.get_board(actor, command.network_id)).board
        directory = await self._directory.execute(actor, command.network_id)
        criteria = await self._criteria.execute(actor, command.network_id)
        criteria_of = {entry.row_ref: entry for entry in criteria.entries}
        site_of = {entry.row_ref: entry for entry in directory.entries}

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
            patient = self._postcodes.locate(inputs.district)
            today = to_london(now).date()

            options: list[NetworkOption] = []
            not_suitable: list[NetworkNotSuitable] = []
            snapshot: list[dict[str, Any]] = []
            for entry in board.entries:
                if entry.row_ref in own_refs:
                    continue
                row = classify_network_row(
                    entry,
                    criteria_of.get(entry.row_ref),
                    site_of.get(entry.row_ref),
                    inputs,
                    now,
                    today,
                )
                snapshot.append(_snapshot_row(entry, row, now))
                if isinstance(row, NetworkNotSuitable):
                    not_suitable.append(row)
                    continue
                if patient is not None and row.position is not None:
                    row = replace(
                        row, travel=await self._travel_time.estimate(patient.lat_lon, row.position)
                    )
                options.append(row)

            await uow.audit.append(
                AuditEntry(
                    action=READ_ACTION,
                    use_case=FILTER_NETWORK_OPTIONS,
                    actor=actor,
                    entity_ids=(case.id,),
                    snapshot={
                        "reference": case.reference,
                        "scope": "network",
                        "services": snapshot,
                    },
                    at=now,
                )
            )
            await uow.commit()

        covered = [entry for entry in criteria.entries if entry.row_ref not in own_refs]
        return FilterNetworkOptionsResult(
            options=tuple(sorted(options, key=option_order_key)),
            not_suitable=tuple(
                sorted(
                    not_suitable,
                    key=lambda item: (
                        item.organisation_name.casefold(),
                        item.service_name.casefold(),
                        item.row_ref,
                    ),
                )
            ),
            generated_at=now,
            system_name=member.settings.system_name,
            pathway_name=member.settings.pathway_name,
            time_zone=member.settings.time_zone,
            patient=None if patient is None else patient.lat_lon,
            not_found=patient is None,
            out_of_area=bool(covered)
            and all(inputs.district not in entry.districts for entry in covered),
        )
