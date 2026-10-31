"""Coverage by postcode district (DEC-1305): who covers what, and the lead's setting of a service.

- `GetCoverageByWindow`: for one part of the day, each district of the tenant with the services that
  cover it, and how many referrals in the last 90 days came from districts nobody covered. Lead and
  executive. A count under 10 is withheld (DEC-393), zero included.
- `GetServiceCoverage`: one service's districts, response target and days, the districts to choose
  from, and which other services already cover them. Lead only.
- `SetServiceCoverage`: replace the service's districts, response target and days. Lead only. The
  service must be the caller's tenant's: another tenant's reads as not found.

The districts to choose from are the tenant's own: every district its services' criteria name or its
services' coverage areas hold. Nothing here reads across tenants.

The count of referrals from uncovered districts comes from the displays of the options list: a
display where no service with current criteria covers the patient's district carries `out_of_area`
(no district is kept, DEC-067). Each case counts once, in the part of the day its first such display
was shown (London time).
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import Final

from overwatch.application.actor import Actor
from overwatch.application.ports.outbound.audit import AuditEntry
from overwatch.application.ports.outbound.clock import Clock
from overwatch.application.ports.outbound.ids import IdGenerator
from overwatch.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from overwatch.application.use_cases.planning_analysis import CHUNK_DAYS, MIN_COUNT, windows
from overwatch.domain.codes import Role
from overwatch.domain.errors import NotAllowed, NotFound
from overwatch.domain.model.flags import SERVICE_FLAG_SUSPENDED
from overwatch.domain.model.service import ServiceProfile
from overwatch.domain.rules.coverage_windows import (
    DAY_CODES,
    WINDOWS,
    DistrictCover,
    StoredCoverage,
    check_setting,
    check_window,
    cover_by_district,
    serves_window,
)
from overwatch.domain.rules.london_time import to_london

UNCOVERED_DAYS: Final = 90
DISPLAY_USE_CASE: Final = "FilterOptions"
SET_USE_CASE: Final = "SetServiceCoverage"
AUDIT_ACTION: Final = "U"
PLANNERS: Final = frozenset({Role.LEAD, Role.EXEC})
LEAD_ONLY: Final = "only the shift lead may set a service's coverage"


@dataclass(frozen=True, slots=True)
class Uncovered:
    count: int | None
    suppressed: bool
    days: int


@dataclass(frozen=True, slots=True)
class CoverageByWindow:
    window: str
    districts: tuple[DistrictCover, ...]
    uncovered: Uncovered


@dataclass(frozen=True, slots=True)
class OtherCover:
    district: str
    service: str


@dataclass(frozen=True, slots=True)
class ServiceCoverageView:
    service_id: str
    service_name: str
    available: tuple[str, ...]
    others: tuple[OtherCover, ...]
    districts: tuple[str, ...]
    response_hours: int | None
    days: tuple[str, ...]


def withheld(count: int) -> Uncovered:
    """A count under MIN_COUNT is withheld (DEC-393): no number, and `suppressed` says so."""
    if count < MIN_COUNT:
        return Uncovered(None, True, UNCOVERED_DAYS)
    return Uncovered(count, False, UNCOVERED_DAYS)


def _profile_days(profile: ServiceProfile) -> tuple[str, ...]:
    days = {day for window in profile.available_times for day in window.days}
    return tuple(code for number, code in enumerate(DAY_CODES) if number in days)


async def _tenant_cover(
    uow: UnitOfWork,
) -> tuple[list[ServiceProfile], dict[str, StoredCoverage], set[str]]:
    """The tenant's active services that are not suspended, what each covers, and every district
    the tenant's services' criteria or coverage areas name."""
    suspended = await uow.flags.services_with_flag(SERVICE_FLAG_SUSPENDED)
    profiles = [item for item in await uow.services.list_active() if item.id not in suspended]
    stored: dict[str, StoredCoverage] = {}
    for profile in profiles:
        found = await uow.services.coverage(profile.id)
        if found is not None:
            stored[profile.id] = found
    criteria = await uow.criteria.current_for_services([item.id for item in profiles])
    universe = {district for item in criteria.values() for district in item.districts}
    universe.update(district for item in stored.values() for district in item.districts)
    return profiles, stored, universe


class GetCoverageByWindow:
    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, actor: Actor, window: str) -> CoverageByWindow:
        if actor.role not in PLANNERS:
            raise NotAllowed("only a shift lead or an executive may read the coverage")
        check_window(window)
        now = self._clock.now()
        first, last = WINDOWS[window]
        async with self._uow_factory() as uow:
            profiles, stored, universe = await _tenant_cover(uow)
            served = [
                (profile.name, stored[profile.id].districts)
                for profile in profiles
                if profile.id in stored
                and serves_window(profile.available_times, stored[profile.id].days, window)
            ]
            cases: set[str] = set()
            seen: set[str] = set()
            for low, high in windows(now - timedelta(days=UNCOVERED_DAYS), now, CHUNK_DAYS):
                for record in await uow.audit.records_between(
                    low, high, frozenset({DISPLAY_USE_CASE})
                ):
                    if record.id in seen:
                        continue
                    seen.add(record.id)
                    entry = record.entry
                    if not (entry.snapshot or {}).get("out_of_area"):
                        continue
                    if first <= to_london(entry.at).hour < last:
                        cases.add(entry.entity_ids[0])
        return CoverageByWindow(
            window=window,
            districts=tuple(cover_by_district(universe, served)),
            uncovered=withheld(len(cases)),
        )


def _check_lead(actor: Actor) -> None:
    if actor.role is not Role.LEAD:
        raise NotAllowed(LEAD_ONLY)


async def _view(uow: UnitOfWork, service_id: str) -> ServiceCoverageView:
    profile = await uow.services.get(service_id)
    mine = await uow.services.coverage(service_id)
    if profile is None or mine is None:
        raise NotFound("no service with this id")
    profiles, stored, universe = await _tenant_cover(uow)
    universe.update(mine.districts)
    others: list[OtherCover] = [
        OtherCover(district, other.name)
        for other in profiles
        if other.id != service_id and other.id in stored
        for district in stored[other.id].districts
    ]
    return ServiceCoverageView(
        service_id=profile.id,
        service_name=profile.name,
        available=tuple(sorted(universe)),
        others=tuple(sorted(others, key=lambda item: (item.district, item.service))),
        districts=mine.districts,
        response_hours=mine.response_hours,
        days=mine.days if mine.days is not None else _profile_days(profile),
    )


class GetServiceCoverage:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def execute(self, actor: Actor, service_id: str) -> ServiceCoverageView:
        _check_lead(actor)
        async with self._uow_factory() as uow:
            return await _view(uow, service_id)


class SetServiceCoverage:
    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock, ids: IdGenerator) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids

    async def execute(
        self, actor: Actor, service_id: str, districts: object, response_hours: object, days: object
    ) -> ServiceCoverageView:
        _check_lead(actor)
        setting = check_setting(districts, response_hours, days)
        async with self._uow_factory() as uow:
            current = await uow.services.coverage(service_id)
            if current is None or await uow.services.get(service_id) is None:
                raise NotFound("no service with this id")
            area_ids = {
                district: self._ids.new_id()
                for district in setting.districts
                if district not in current.districts
            }
            await uow.services.set_coverage(service_id, setting, area_ids)
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_ACTION,
                    use_case=SET_USE_CASE,
                    actor=actor,
                    entity_ids=(service_id, *area_ids.values()),
                    snapshot={
                        "districts": list(setting.districts),
                        "response_hours": setting.response_hours,
                        "days": list(setting.days),
                    },
                    at=self._clock.now(),
                )
            )
            await uow.commit()
        async with self._uow_factory() as uow:
            return await _view(uow, service_id)
