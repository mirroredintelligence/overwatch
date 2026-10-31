"""FilterOptions: the services that may take a case, and why the others may not (U12).

A filter, never a ranking: the options are the services that pass the hard criteria and are
accepting or limited or over capacity, sorted by travel (lowest low end first, no travel last, then
name). Every service the advisor could have been shown is written to one audit entry, with the
status, number, data age and criteria version of each, so the record says what the advisor saw
(domain-rules 4.1, DEC-035, DEC-042).

Rules: check_hard_criteria (D20) and is_review_overdue (D21) for the criteria; compute_status
through QueryBoard for the status and number; assess the data age against the stale limit (D05).
The patient's position is the postcode centroid of the case's district; a service with no position
has no travel. Only the district is stored on a case (DEC-067), so the snapshot holds no postcode
and no district.

Decisions: DEC-290 (roles, the read and its audit, no replay; its Assumed list holds the reason
and warning texts).
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from types import MappingProxyType
from typing import Any, Final

from diucs.application.actor import Actor
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.geo import (
    LatLon,
    Located,
    PostcodeLocator,
    TravelRange,
    TravelTime,
)
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.open_case import check_role, missing_fields
from diucs.application.use_cases.query_board import BoardEntry, QueryBoard, QueryBoardQuery
from diucs.domain.codes import AgeBand, NeedCategory, ServiceCategory, Status
from diucs.domain.errors import Conflict, NotFound, ValidationFailed
from diucs.domain.model.criteria import ServiceCriteria
from diucs.domain.model.flags import SERVICE_FLAG_SUSPENDED
from diucs.domain.rules.criteria_filter import check_hard_criteria
from diucs.domain.rules.criteria_workflow import is_review_overdue
from diucs.domain.rules.district_choice import candidate_districts
from diucs.domain.rules.freshness import STALE_WARNING_AFTER, data_age_text
from diucs.domain.rules.london_time import to_london

FILTER_OPTIONS: Final = "FilterOptions"
READ_ACTION: Final = "R"
NOT_ACCEPTING_REASON: Final = "not accepting"
OUT_OF_HOURS_REASON: Final = "out of hours"
OUTSIDE_CRITERIA_REASON: Final = "outside criteria"
CRITERIA_NOT_CURRENT_REASON: Final = "criteria not current"
SUSPENDED_REASON: Final = "suspended. Phone to confirm."
NOT_UPDATED_NO_AGE_REASON: Final = "not updated. Phone to confirm."
LIMITED_WARNING: Final = "Limited: phone to confirm"
OVER_CAPACITY_WARNING: Final = "Over capacity now. Phone to confirm before offering."
OLD_DATA_WARNING: Final = "Data is over 2 hrs old. Consider phoning."
CRITERIA_NOT_REVIEWED_WARNING: Final = "Criteria not reviewed"
COVERS_POSTCODE: Final = "Covers this postcode"
SHOWN_AS_OPTION: Final = "option"
SHOWN_AS_NOT_SUITABLE: Final = "not-suitable"

NEED_PHRASES: Final[Mapping[NeedCategory, str]] = MappingProxyType(
    {
        NeedCategory.FALL_NO_INJURY: "fall",
        NeedCategory.FRAILTY: "frailty",
        NeedCategory.WOUND_CARE: "wound care",
        NeedCategory.IV_THERAPY: "IV therapy",
        NeedCategory.PALLIATIVE: "palliative",
        NeedCategory.DEMENTIA: "dementia",
        NeedCategory.SUSPECTED_FRACTURE: "suspected fracture",
        NeedCategory.HEAD_INJURY_ANTICOAGULANTS: "head injury on anticoagulants",
        NeedCategory.INFECTION_ISOLATION: "infection isolation",
    }
)
"""The lower-case phrase for each need, as the case summary and the fit lines write it."""


def need_phrase(need: NeedCategory) -> str:
    return NEED_PHRASES[need]


@dataclass(frozen=True, slots=True)
class FilterOptionsCommand:
    idempotency_key: str
    """Not used for replay: each display is its own audit record (DEC-290). Kept for the command
    shape every other use case takes, and for the caller's own correlation."""
    actor: Actor
    case_id: str


@dataclass(frozen=True, slots=True)
class Option:
    service_id: str
    name: str
    status: Status
    effective_available: int | None
    over_by: int | None
    unit_label: str
    data_age: timedelta | None
    travel: TravelRange | None
    fits: tuple[str, ...]
    warnings: tuple[str, ...]
    criteria_id: str
    criteria_version: int
    category: ServiceCategory | None = None
    position: LatLon | None = None
    """The place of a fixed site, from its Location; None for a service with no position."""


@dataclass(frozen=True, slots=True)
class NotSuitable:
    service_id: str
    name: str
    reason: str


@dataclass(frozen=True, slots=True)
class FilterOptionsResult:
    options: tuple[Option, ...]
    not_suitable: tuple[NotSuitable, ...]
    generated_at: datetime
    patient: LatLon | None = None
    """The centre of the case's postcode district (only the district is stored, DEC-067)."""
    not_found: bool = False
    """The locator does not know the case's district."""
    out_of_area: bool = False
    """No service with current criteria covers the case's district."""
    districts: tuple[str, ...] = ()
    """The districts to offer as chips when `not_found` or `out_of_area` is true, and none otherwise
    (W50, W9H DEC-1045): the districts this tenant's unsuspended services cover that the locator can
    place, nearest first (or the case's own postcode area first when it has no place). They are the
    services' configuration, never anything about the case."""


def status_reason(status: Status, data_age: timedelta | None) -> str | None:
    """Why a service with this status may not take the case, or None when its status allows it.
    Not accepting, out of hours and not updated are not suitable; limited and over capacity are
    options with a warning (see status_warnings)."""
    if status is Status.NOT_ACCEPTING:
        return NOT_ACCEPTING_REASON
    if status is Status.OUT_OF_HOURS:
        return OUT_OF_HOURS_REASON
    if status is Status.NOT_UPDATED:
        if data_age is None:
            return NOT_UPDATED_NO_AGE_REASON
        return f"not updated for {data_age_text(data_age).removesuffix(' ago')}. Phone to confirm."
    return None


def status_warnings(status: Status) -> tuple[str, ...]:
    if status is Status.LIMITED:
        return (LIMITED_WARNING,)
    if status is Status.OVER_CAPACITY:
        return (OVER_CAPACITY_WARNING,)
    return ()


def data_age_warnings(data_age: timedelta | None) -> tuple[str, ...]:
    """Warned only when the figure is older than the stale limit, never at exactly the limit."""
    if data_age is not None and data_age > STALE_WARNING_AFTER:
        return (OLD_DATA_WARNING,)
    return ()


def criteria_warnings(criteria: ServiceCriteria, today: date) -> tuple[str, ...]:
    if is_review_overdue(criteria, today):
        return (CRITERIA_NOT_REVIEWED_WARNING,)
    return ()


def fits_for(criteria: ServiceCriteria, needs: tuple[NeedCategory, ...]) -> tuple[str, ...]:
    """The fit lines of an option: the postcode is covered, and the needs the service accepts."""
    fits = [COVERS_POSTCODE]
    taken = [need_phrase(need) for need in needs if need in criteria.accepts]
    if taken:
        fits.append(f"Takes {', '.join(taken)}")
    return tuple(fits)


def option_order_key(option: Option) -> tuple[int, int, str, str]:
    """Travel low end first; no travel after every option with travel; then name, then id."""
    if option.travel is None:
        return (1, 0, option.name, option.service_id)
    return (0, option.travel.low_minutes, option.name, option.service_id)


def _verdict(
    entry: BoardEntry,
    data_age: timedelta | None,
    suspended: set[str],
    current: ServiceCriteria | None,
    age_band: AgeBand,
    district: str,
    needs: tuple[NeedCategory, ...],
) -> tuple[str | None, tuple[str, ...]]:
    """Why the service may not take the case (None when it may), and the warnings of the criteria
    check. Suspended first, so a suspended service is never offered; then the status; then the
    criteria. Fails closed: no current criteria version is not suitable."""
    if entry.service_id in suspended:
        return SUSPENDED_REASON, ()
    reason = status_reason(entry.status, data_age)
    if reason is not None:
        return reason, ()
    if current is None:
        return CRITERIA_NOT_CURRENT_REASON, ()
    result = check_hard_criteria(current, age_band, district, needs)
    if not result.passes:
        return OUTSIDE_CRITERIA_REASON, ()
    return None, result.warnings


def _snapshot_row(
    entry: BoardEntry,
    number: int | None,
    data_age: timedelta | None,
    criteria: ServiceCriteria | None,
    shown_as: str,
) -> dict[str, Any]:
    return {
        "id": entry.service_id,
        "status": entry.status.value,
        "number": number,
        "data_age_seconds": None if data_age is None else int(data_age.total_seconds()),
        "criteria_version": None if criteria is None else criteria.version,
        "shown_as": shown_as,
    }


class FilterOptions:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        query_board: QueryBoard,
        postcodes: PostcodeLocator,
        travel_time: TravelTime,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._query_board = query_board
        self._postcodes = postcodes
        self._travel_time = travel_time

    async def execute(self, command: FilterOptionsCommand) -> FilterOptionsResult:
        check_role(command.actor)
        # The board is read in its own unit of work, so it is read before this one opens: two units
        # cannot be open in one context (P06).
        board = await self._query_board.execute(QueryBoardQuery(command.actor))

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
            age_band = case.age_band
            district = case.postcode
            if age_band is None or district is None:  # missing_fields has refused both
                raise ValidationFailed("case", "is incomplete")

            now = self._clock.now()
            service_ids = [entry.service_id for entry in board.entries]
            criteria = await uow.criteria.current_for_services(service_ids)
            suspended = await uow.flags.services_with_flag(SERVICE_FLAG_SUSPENDED)
            positions = await uow.positions.get_many(service_ids)
            patient = self._postcodes.locate(district)
            today = to_london(now).date()

            options: list[Option] = []
            not_suitable: list[NotSuitable] = []
            rows: list[dict[str, Any]] = []
            for entry in board.entries:
                data_age = None if entry.reported_at is None else now - entry.reported_at
                number = entry.effective_available
                if number is None:
                    number = entry.used
                current = criteria.get(entry.service_id)
                reason, check_warnings = _verdict(
                    entry, data_age, suspended, current, age_band, district, case.needs
                )
                if reason is not None or current is None:
                    shown = reason if reason is not None else CRITERIA_NOT_CURRENT_REASON
                    not_suitable.append(NotSuitable(entry.service_id, entry.name, shown))
                    rows.append(
                        _snapshot_row(entry, number, data_age, current, SHOWN_AS_NOT_SUITABLE)
                    )
                    continue

                travel = None
                site = positions.get(entry.service_id)
                if patient is not None and site is not None:
                    travel = await self._travel_time.estimate(patient.lat_lon, site)
                warnings = (
                    check_warnings
                    + status_warnings(entry.status)
                    + data_age_warnings(data_age)
                    + criteria_warnings(current, today)
                )
                options.append(
                    Option(
                        service_id=entry.service_id,
                        name=entry.name,
                        status=entry.status,
                        effective_available=entry.effective_available,
                        over_by=entry.over_by,
                        unit_label=entry.unit_label,
                        data_age=data_age,
                        travel=travel,
                        fits=fits_for(current, case.needs),
                        warnings=warnings,
                        criteria_id=current.id,
                        criteria_version=current.version,
                        category=entry.category,
                        position=site,
                    )
                )
                rows.append(_snapshot_row(entry, number, data_age, current, SHOWN_AS_OPTION))

            await uow.audit.append(
                AuditEntry(
                    action=READ_ACTION,
                    use_case=FILTER_OPTIONS,
                    actor=command.actor,
                    entity_ids=(case.id, *service_ids),
                    snapshot={"reference": case.reference, "services": rows},
                    at=now,
                )
            )
            await uow.commit()

        not_found = patient is None
        out_of_area = bool(criteria) and all(
            district not in item.districts for item in criteria.values()
        )
        return FilterOptionsResult(
            options=tuple(sorted(options, key=option_order_key)),
            not_suitable=tuple(sorted(not_suitable, key=lambda item: (item.name, item.service_id))),
            generated_at=now,
            patient=None if patient is None else patient.lat_lon,
            not_found=not_found,
            out_of_area=out_of_area,
            districts=(
                self._district_choices(criteria, suspended, patient, district)
                if not_found or out_of_area
                else ()
            ),
        )

    def _district_choices(
        self,
        criteria: Mapping[str, ServiceCriteria],
        suspended: Collection[str],
        patient: Located | None,
        district: str,
    ) -> tuple[str, ...]:
        """The districts to offer: the unsuspended services' districts that the locator can place.
        A district it cannot place would only lead back to the same screen."""
        places: dict[str, tuple[float, float]] = {}
        for service_id, item in criteria.items():
            if service_id in suspended:
                continue
            for covered in item.districts:
                centre = self._postcodes.district_centroid(covered)
                if centre is not None:
                    places[covered] = (centre.lat, centre.lon)
        origin = None if patient is None else (patient.lat_lon.lat, patient.lat_lon.lon)
        return candidate_districts(places, origin=origin, case_district=district)
