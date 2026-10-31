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

import asyncio
from collections.abc import Callable, Collection, Iterable, Mapping
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
from diucs.domain.rules.coverage import coverage_circle
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
ROAD_LEG_HOW: Final = "Typical weekday afternoon. The spread is from traffic."
STRAIGHT_LEG_HOW: Final = (
    "A straight-line estimate, not a road route. The spread allows for slower roads."
)
ROUTING_SOURCE_PREFIX: Final = "Routing data"
SHOWN_AS_OPTION: Final = "option"
SHOWN_AS_NOT_SUITABLE: Final = "not-suitable"

_REASON_CODES: Final[tuple[tuple[str, str], ...]] = (
    (NOT_ACCEPTING_REASON, "not-accepting"),
    (OUT_OF_HOURS_REASON, "out-of-hours"),
    (OUTSIDE_CRITERIA_REASON, "outside-criteria"),
    (CRITERIA_NOT_CURRENT_REASON, "criteria-not-current"),
    ("suspended", "suspended"),
    ("not updated", "not-updated"),
)
"""The closed set of codes a snapshot keeps for why a service was not suitable (W9G). The reason
text carries an age ("not updated for 2 hrs"); the code never does."""


def reason_code(reason: str) -> str:
    """The code of a reason text, for the snapshot. Any other text is refused."""
    for start, code in _REASON_CODES:
        if reason.startswith(start):
            return code
    raise ValueError("not a reason a service is not suitable")


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
class TravelLeg:
    """One leg of a travel estimate as the travel details table shows it (W50): the leg, its range
    in minutes, how it was measured and where the range came from."""

    label: str
    low_minutes: int
    high_minutes: int
    how: str
    source: str


@dataclass(frozen=True, slots=True)
class Coverage:
    """The circle a visiting service is drawn with (DEC-1175): its centre and a radius in whole
    kilometres. A picture of where it goes, not a boundary."""

    lat: float
    lon: float
    radius_km: int


def travel_legs(name: str, travel: TravelRange | None) -> tuple[TravelLeg, ...]:
    """The legs of a travel range: one, from the patient to the service. Only a range that came from
    the routing engine is called a road route; the straight-line fallback says what it is."""
    if travel is None:
        return ()
    routed = travel.source.startswith(ROUTING_SOURCE_PREFIX)
    return (
        TravelLeg(
            label=f"Patient to {name}, by road"
            if routed
            else f"Patient to {name}, in a straight line",
            low_minutes=travel.low_minutes,
            high_minutes=travel.high_minutes,
            how=ROAD_LEG_HOW if routed else STRAIGHT_LEG_HOW,
            source=travel.source,
        ),
    )


def coverage_of(
    districts: Iterable[str], centre_of: Callable[[str], LatLon | None]
) -> Coverage | None:
    """The circle of the districts a service covers that the locator can place; None when it can
    place none. A district it cannot place is left out rather than guessed."""
    points = [
        (place.lat, place.lon)
        for district in sorted(set(districts))
        if (place := centre_of(district)) is not None
    ]
    circle = coverage_circle(points)
    return None if circle is None else Coverage(circle.lat, circle.lon, circle.radius_km)


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
    phone: str | None = None
    """The service's own number, to phone to confirm (Q5, DEC-1100): the work phone of its profile.
    None when the service has none; the screen then says "Phone to confirm" and no number."""
    coverage: Coverage | None = None
    """A visiting service's circle (DEC-1175): set for a service with no site and districts the
    locator can place."""
    legs: tuple[TravelLeg, ...] = ()
    """The travel range as legs (W50)."""
    organisation: str | None = None
    """The organisation of a network service (KI-349, KI-794): set only on a network option, which
    is read only. None for the viewer's own services."""
    organisation_source: str | None = None
    """Where a network service's directory entry came from, as the card says it."""


@dataclass(frozen=True, slots=True)
class NotSuitable:
    service_id: str
    name: str
    reason: str


@dataclass(frozen=True, slots=True)
class _Candidate:
    """An option read in the unit of work, before its travel is estimated (KI-350): the estimate is
    awaited after the unit has closed, so a slow routing engine never holds a transaction open."""

    entry: BoardEntry
    current: ServiceCriteria
    site: LatLon | None
    covers: tuple[str, ...]
    phone: str | None
    fits: tuple[str, ...]
    warnings: tuple[str, ...]


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
    reason: str | None = None,
    order: int | None = None,
) -> dict[str, Any]:
    """One service of a display. `over_by` is how far over capacity it was (the used count in
    `number` is not that figure, DEC-391) and `reason` is the code of why it was not suitable: both
    are read by a clinician who is shown what the advisor saw (W9G, H-190). `name` is the name the
    advisor saw, so a replay shows it as it was (KI-474), and `order` is the position an option was
    shown at, nearest first, so the replay and the planning analysis know which was first (H-193,
    KI-476); a service that was not suitable is in no order."""
    row: dict[str, Any] = {
        "id": entry.service_id,
        "name": entry.name,
        "status": entry.status.value,
        "number": number,
        "data_age_seconds": None if data_age is None else int(data_age.total_seconds()),
        "criteria_version": None if criteria is None else criteria.version,
        "shown_as": shown_as,
        "over_by": entry.over_by,
    }
    if reason is not None:
        row["reason"] = reason_code(reason)
    if order is not None:
        row["order"] = order
    return row


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
            covered = await uow.positions.coverage_districts(service_ids)
            phones = await uow.services.work_phones(service_ids)
            patient = self._postcodes.locate(district)
            today = to_london(now).date()

            candidates: list[_Candidate] = []
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
                        _snapshot_row(
                            entry, number, data_age, current, SHOWN_AS_NOT_SUITABLE, shown
                        )
                    )
                    continue

                site = positions.get(entry.service_id)
                warnings = (
                    check_warnings
                    + status_warnings(entry.status)
                    + data_age_warnings(data_age)
                    + criteria_warnings(current, today)
                )
                candidates.append(
                    _Candidate(
                        entry=entry,
                        current=current,
                        site=site,
                        covers=covered.get(entry.service_id, ()),
                        phone=phones.get(entry.service_id),
                        fits=fits_for(current, case.needs),
                        warnings=warnings,
                    )
                )
                rows.append(_snapshot_row(entry, number, data_age, current, SHOWN_AS_OPTION))

            reference = case.reference
            case_id = case.id

        # The unit has closed: the travel estimates are awaited here, all at once, so an engine
        # that is slow or down costs one timeout and not one per service (KI-350).
        ranges = await asyncio.gather(
            *(self._travel_range(patient, candidate.site) for candidate in candidates)
        )
        options = sorted(
            (
                self._option(candidate, travel, now)
                for candidate, travel in zip(candidates, ranges, strict=True)
            ),
            key=option_order_key,
        )
        # The display is written down once the order the advisor will see it in is known: each
        # option's position is in its row (H-193). It is written in a unit of its own, and before
        # the answer leaves, so an advisor is never shown a display that is not on the record.
        shown_at = {option.service_id: position for position, option in enumerate(options, 1)}
        for row in rows:
            if row["shown_as"] == SHOWN_AS_OPTION:
                row["order"] = shown_at[row["id"]]
        async with self._uow_factory() as audit_uow:
            await audit_uow.audit.append(
                AuditEntry(
                    action=READ_ACTION,
                    use_case=FILTER_OPTIONS,
                    actor=command.actor,
                    entity_ids=(case_id, *service_ids),
                    snapshot={"reference": reference, "services": rows},
                    at=now,
                )
            )
            await audit_uow.commit()
        not_found = patient is None
        out_of_area = bool(criteria) and all(
            district not in item.districts for item in criteria.values()
        )
        return FilterOptionsResult(
            options=tuple(options),
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

    async def _travel_range(
        self, patient: Located | None, site: LatLon | None
    ) -> TravelRange | None:
        if patient is None or site is None:
            return None
        return await self._travel_time.estimate(patient.lat_lon, site)

    def _option(self, candidate: _Candidate, travel: TravelRange | None, now: datetime) -> Option:
        entry = candidate.entry
        data_age = None if entry.reported_at is None else now - entry.reported_at
        return Option(
            service_id=entry.service_id,
            name=entry.name,
            status=entry.status,
            effective_available=entry.effective_available,
            over_by=entry.over_by,
            unit_label=entry.unit_label,
            data_age=data_age,
            travel=travel,
            fits=candidate.fits,
            warnings=candidate.warnings,
            criteria_id=candidate.current.id,
            criteria_version=candidate.current.version,
            category=entry.category,
            position=candidate.site,
            phone=candidate.phone,
            coverage=(
                None
                if candidate.site is not None
                else coverage_of(candidate.covers, self._district_place)
            ),
            legs=travel_legs(entry.name, travel),
        )

    def _district_place(self, district: str) -> LatLon | None:
        return self._postcodes.district_centroid(district)

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
