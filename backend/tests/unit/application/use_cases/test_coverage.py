"""The coverage use cases (DEC-1305) on a hand-made unit of work: who covers what by time of day,
the withheld count, the lead's view and save. The stored behaviour (Neo4j, tenants) is in
tests/integration/application/test_coverage.py; here only the rules the use cases add.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, time
from types import SimpleNamespace
from typing import Any

import pytest

from overwatch.adapters.testing.fixed_clock import FixedClock
from overwatch.adapters.testing.fixed_ids import SequentialIds
from overwatch.application.actor import Actor
from overwatch.application.ports.outbound.audit import AuditEntry, AuditRecord
from overwatch.application.use_cases.coverage import (
    GetCoverageByWindow,
    GetServiceCoverage,
    SetServiceCoverage,
    withheld,
)
from overwatch.domain.codes import Cadence, Channel, Measure, Role, ServiceCategory
from overwatch.domain.errors import NotAllowed, NotFound, ValidationFailed
from overwatch.domain.model.service import AvailableTime, ServiceProfile
from overwatch.domain.rules.coverage_windows import CoverageSetting, StoredCoverage
from tests.support.actors import ACTOR_TENANT

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)  # a Monday, GMT


def actor(role: Role) -> Actor:
    return Actor(role, "prac-1", None, "web", frozenset(), ACTOR_TENANT)


def profile(
    service_id: str, name: str, times: tuple[AvailableTime, ...] | None = None
) -> ServiceProfile:
    return ServiceProfile(
        id=service_id,
        name=name,
        category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
        measure=Measure.REFERRALS_ACCEPTABLE,
        unit_label="referrals",
        established_capacity=8,
        can_exceed_established=False,
        usual_range=(0, 8),
        cadence=Cadence.EVERY_2_HRS,
        available_times=times or (AvailableTime.every_day_all_day(),),
        channel=Channel.TEXT,
    )


@dataclass
class World:
    profiles: dict[str, ServiceProfile] = field(default_factory=dict)
    stored: dict[str, StoredCoverage] = field(default_factory=dict)
    criteria: dict[str, frozenset[str]] = field(default_factory=dict)
    suspended: set[str] = field(default_factory=set)
    records: list[AuditRecord] = field(default_factory=list)
    written: list[tuple[str, CoverageSetting, Mapping[str, str]]] = field(default_factory=list)
    audited: list[AuditEntry] = field(default_factory=list)
    committed: int = 0

    def factory(self) -> Any:
        world = self

        class Services:
            async def get(self, service_id: str) -> ServiceProfile | None:
                return world.profiles.get(service_id)

            async def list_active(self) -> list[ServiceProfile]:
                return sorted(world.profiles.values(), key=lambda item: item.name)

            async def coverage(self, service_id: str) -> StoredCoverage | None:
                return world.stored.get(service_id)

            async def set_coverage(
                self, service_id: str, setting: CoverageSetting, area_ids: Mapping[str, str]
            ) -> None:
                world.written.append((service_id, setting, area_ids))
                world.stored[service_id] = StoredCoverage(
                    setting.districts, setting.response_hours, setting.days
                )

        class Flags:
            async def services_with_flag(self, code: str) -> set[str]:
                return set(world.suspended)

        class Criteria:
            async def current_for_services(self, ids: list[str]) -> dict[str, Any]:
                return {
                    sid: SimpleNamespace(districts=world.criteria[sid])
                    for sid in ids
                    if sid in world.criteria
                }

        class Audit:
            async def records_between(
                self, start: datetime, end: datetime, use_cases: frozenset[str]
            ) -> list[AuditRecord]:
                return [r for r in world.records if start <= r.entry.at <= end]

            async def append(self, entry: AuditEntry) -> None:
                world.audited.append(entry)

        class Unit:
            services = Services()
            flags = Flags()
            criteria = Criteria()
            audit = Audit()

            async def __aenter__(self) -> Unit:
                return self

            async def __aexit__(self, *exc: object) -> None:
                return None

            async def commit(self) -> None:
                world.committed += 1

        return Unit


def display(case: str, at: datetime, *, out_of_area: bool) -> AuditRecord:
    snapshot: dict[str, Any] = {"reference": "R", "services": []}
    if out_of_area:
        snapshot["out_of_area"] = True
    entry = AuditEntry("R", "FilterOptions", actor(Role.ADVISOR), (case,), snapshot, at)
    return AuditRecord(f"{case}-{at.isoformat()}", entry, "h", "p")


def world_with_two_services() -> World:
    world = World()
    world.profiles = {
        "west": profile("west", "UCR West", (AvailableTime.every_day(time(8), time(18)),)),
        "east": profile("east", "UCR East"),
    }
    world.stored = {
        "west": StoredCoverage(("DT1", "DT2", "DT3"), 2, ("mon", "tue")),
        "east": StoredCoverage(("DT3",), 4, None),
    }
    world.criteria = {"west": frozenset({"DT1", "DT5"}), "east": frozenset({"DT3"})}
    return world


async def by_window(world: World, window: str, role: Role = Role.LEAD) -> Any:
    return await GetCoverageByWindow(world.factory(), FixedClock(NOW)).execute(actor(role), window)


async def test_each_district_of_the_tenant_is_listed_with_who_covers_it_all_day() -> None:
    result = await by_window(world_with_two_services(), "all")

    assert {item.district: item.services for item in result.districts} == {
        "DT1": ("UCR West",),
        "DT2": ("UCR West",),
        "DT3": ("UCR East", "UCR West"),
        "DT5": (),
    }


async def test_a_service_that_is_not_out_at_night_does_not_cover_the_night() -> None:
    result = await by_window(world_with_two_services(), "night")

    assert {item.district: item.services for item in result.districts} == {
        "DT1": (),
        "DT2": (),
        "DT3": ("UCR East",),
        "DT5": (),
    }


async def test_a_suspended_service_covers_nothing() -> None:
    world = world_with_two_services()
    world.suspended = {"east"}

    result = await by_window(world, "night")

    assert all(item.services == () for item in result.districts)


async def test_an_executive_may_read_and_any_other_role_may_not() -> None:
    assert (await by_window(world_with_two_services(), "all", Role.EXEC)).window == "all"
    with pytest.raises(NotAllowed):
        await by_window(world_with_two_services(), "all", Role.ADVISOR)


async def test_an_unknown_window_is_refused_naming_it() -> None:
    with pytest.raises(ValidationFailed) as refused:
        await by_window(world_with_two_services(), "dawn")
    assert refused.value.field == "window"


@pytest.mark.parametrize(("count", "shown"), [(0, None), (9, None), (10, 10), (31, 31)])
def test_a_count_under_ten_is_withheld_zero_included(count: int, shown: int | None) -> None:
    result = withheld(count)

    assert result.count == shown
    assert result.suppressed is (shown is None)
    assert result.days == 90


async def test_uncovered_counts_each_case_once_over_ninety_days_in_the_window() -> None:
    world = world_with_two_services()
    morning = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
    night = datetime(2026, 10, 21, 2, 0, tzinfo=UTC)
    for number in range(12):
        # Each case is displayed twice: it counts once.
        world.records.append(display(f"case-{number}", morning, out_of_area=True))
        world.records.append(
            display(f"case-{number}", morning.replace(minute=30), out_of_area=True)
        )
    world.records.append(display("covered", morning, out_of_area=False))
    world.records.append(
        display("too-old", datetime(2026, 7, 1, 9, 0, tzinfo=UTC), out_of_area=True)
    )
    world.records.append(display("night-1", night, out_of_area=True))

    whole = await by_window(world, "all")
    morning_only = await by_window(world, "morning")
    night_only = await by_window(world, "night")

    assert (whole.uncovered.count, whole.uncovered.suppressed) == (13, False)
    assert (morning_only.uncovered.count, morning_only.uncovered.suppressed) == (12, False)
    assert (night_only.uncovered.count, night_only.uncovered.suppressed) == (None, True)


async def test_the_lead_sees_the_service_the_districts_to_choose_and_who_else_covers() -> None:
    world = world_with_two_services()

    view = await GetServiceCoverage(world.factory()).execute(actor(Role.LEAD), "west")

    assert (view.service_id, view.service_name) == ("west", "UCR West")
    assert view.districts == ("DT1", "DT2", "DT3")
    assert view.available == ("DT1", "DT2", "DT3", "DT5")
    assert [(o.district, o.service) for o in view.others] == [("DT3", "UCR East")]
    assert (view.response_hours, view.days) == (2, ("mon", "tue"))


async def test_before_the_lead_sets_the_days_the_profiles_days_are_shown_with_no_target() -> None:
    world = world_with_two_services()

    view = await GetServiceCoverage(world.factory()).execute(actor(Role.LEAD), "east")

    assert view.response_hours == 4
    assert view.days == ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    world.stored["east"] = StoredCoverage((), None, None)
    again = await GetServiceCoverage(world.factory()).execute(actor(Role.LEAD), "east")
    assert again.response_hours is None


async def test_only_the_lead_reads_or_sets_and_an_unknown_service_is_not_found() -> None:
    world = world_with_two_services()
    for role in (Role.EXEC, Role.ADVISOR):
        with pytest.raises(NotAllowed):
            await GetServiceCoverage(world.factory()).execute(actor(role), "west")
        with pytest.raises(NotAllowed):
            await SetServiceCoverage(world.factory(), FixedClock(NOW), SequentialIds()).execute(
                actor(role), "west", ["DT1"], 2, ["mon"]
            )
    with pytest.raises(NotFound):
        await GetServiceCoverage(world.factory()).execute(actor(Role.LEAD), "nobody")
    with pytest.raises(NotFound):
        await SetServiceCoverage(world.factory(), FixedClock(NOW), SequentialIds()).execute(
            actor(Role.LEAD), "nobody", ["DT1"], 2, ["mon"]
        )
    assert world.written == []


async def test_a_save_stores_the_setting_gives_new_districts_ids_audits_and_returns_the_view() -> (
    None
):
    world = world_with_two_services()
    save = SetServiceCoverage(world.factory(), FixedClock(NOW), SequentialIds())

    view = await save.execute(actor(Role.LEAD), "west", ["dt4", "DT1"], 6, ["sat", "mon"])

    ((service_id, setting, area_ids),) = world.written
    assert service_id == "west"
    assert setting == CoverageSetting(("DT1", "DT4"), 6, ("mon", "sat"))
    assert set(area_ids) == {"DT4"}  # DT1 is covered already: it keeps its Location
    assert world.committed == 1
    (entry,) = world.audited
    assert entry.use_case == "SetServiceCoverage"
    assert entry.snapshot == {
        "districts": ["DT1", "DT4"],
        "response_hours": 6,
        "days": ["mon", "sat"],
    }
    assert (view.districts, view.response_hours, view.days) == (("DT1", "DT4"), 6, ("mon", "sat"))


async def test_a_bad_setting_writes_nothing() -> None:
    world = world_with_two_services()
    save = SetServiceCoverage(world.factory(), FixedClock(NOW), SequentialIds())

    with pytest.raises(ValidationFailed):
        await save.execute(actor(Role.LEAD), "west", ["DT1"], 99, ["mon"])

    assert world.written == []
    assert world.committed == 0
