"""FindServices (DEC-1379): the map and the "not suitable" screens. Each found service carries its
site position and the area it covers; every board service that was not found comes back with its
reasons. Pure: fakes for the board, the unit of work, the locator and the travel time. Browse only:
the audit entry holds service ids, status, figure state and criteria version, never the postcode,
district, age band, needs, urgency or a reason. Samples only."""

import logging
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from overwatch.application.actor import Actor
from overwatch.application.ports.outbound.geo import LatLon, Located, TravelRange
from overwatch.application.use_cases.find_services import (
    REASON_NO_CRITERIA,
    REASON_SUSPENDED,
    FindServices,
    FindServicesCommand,
    match_services,
    split_services,
)
from overwatch.application.use_cases.query_board import Board, BoardEntry
from overwatch.domain.codes import (
    AgeBand,
    Cadence,
    CriteriaStatus,
    NeedCategory,
    Role,
    ServiceCategory,
    Status,
    Urgency,
)
from overwatch.domain.model.criteria import ServiceCriteria
from overwatch.domain.rules.pressure import Pressure

NOW = datetime(2026, 11, 10, 14, 0, tzinfo=UTC)
TODAY = date(2026, 11, 10)
POSTCODE = "DT4 8XX"
DISTRICT = "DT4"


def _entry(service_id: str, name: str, **changes: object) -> BoardEntry:
    base = BoardEntry(
        service_id=service_id,
        name=name,
        category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
        status=Status.ACCEPTING,
        effective_available=5,
        over_by=None,
        used=5,
        established=10,
        pending=0,
        unit_label="referrals",
        comment="",
        reported_at=NOW - timedelta(minutes=20),
        next_due_at=NOW + timedelta(hours=1),
        was_due_at=None,
        cadence=Cadence.EVERY_2_HRS,
    )
    return replace(base, **changes)  # type: ignore[arg-type]


def _criteria(service_id: str, **changes: object) -> ServiceCriteria:
    base = ServiceCriteria(
        id=f"crit-{service_id}",
        service_id=service_id,
        version=4,
        status=CriteriaStatus.CURRENT,
        age_min=16,
        age_max=None,
        districts=frozenset({DISTRICT}),
        accepts=frozenset({NeedCategory.FRAILTY}),
        excludes=frozenset(),
        review_by=date(2026, 12, 31),
        owner_role_id="role-lead",
    )
    return replace(base, **changes)  # type: ignore[arg-type]


ACTOR = Actor(Role.ADVISOR_V2, None, None, "app", frozenset(), "tenant-a")
COMMAND = FindServicesCommand(
    actor=ACTOR,
    postcode=POSTCODE,
    age_band=AgeBand.A80_PLUS,
    needs=(NeedCategory.FRAILTY,),
    urgency=Urgency.TODAY,
)
SUSPENDED = {"svc-suspended"}


class _Clock:
    def now(self) -> datetime:
        return NOW


class _Board:
    def __init__(self, entries: tuple[BoardEntry, ...]) -> None:
        self._entries = entries

    async def execute(self, query: object) -> Board:
        return Board(
            entries=self._entries,
            pressure=Pressure.NORMAL,
            all_limited_or_worse=False,
            generated_at=NOW,
        )


@dataclass
class _Audit:
    entries: list[Any] = field(default_factory=list)

    async def append(self, entry: Any) -> None:
        self.entries.append(entry)


class _Criteria:
    def __init__(self, rows: dict[str, ServiceCriteria]) -> None:
        self.rows = rows

    async def current_for_services(self, ids: list[str]) -> dict[str, ServiceCriteria]:
        return {i: self.rows[i] for i in ids if i in self.rows}


class _Flags:
    def __init__(self, suspended: set[str]) -> None:
        self._suspended = suspended

    async def services_with_flag(self, code: str) -> set[str]:
        return self._suspended


class _Services:
    async def work_phones(self, ids: list[str]) -> dict[str, str]:
        return {}


class _Positions:
    def __init__(self, sites: dict[str, LatLon], covered: dict[str, tuple[str, ...]]) -> None:
        self.sites = sites
        self.covered = covered
        self.asked: list[list[str]] = []

    async def get_many(self, ids: list[str]) -> dict[str, LatLon]:
        self.asked.append(list(ids))
        return {i: self.sites[i] for i in ids if i in self.sites}

    async def coverage_districts(self, ids: list[str]) -> dict[str, tuple[str, ...]]:
        self.asked.append(list(ids))
        return {i: self.covered[i] for i in ids if i in self.covered}


class _Locator:
    CENTRES = {"DT1": LatLon(50.71, -2.44), "DT2": LatLon(50.73, -2.46)}

    def locate(self, postcode: str) -> Located | None:
        return Located(LatLon(50.70, -2.45), approximate=True)

    def district_centroid(self, district: str) -> LatLon | None:
        return self.CENTRES.get(district)


class _Travel:
    async def estimate(self, origin: LatLon, destination: LatLon) -> TravelRange:
        return TravelRange(5, 10, "test")


class _Uow:
    def __init__(self, world: _World) -> None:
        self.criteria = world.criteria
        self.flags = world.flags
        self.services = _Services()
        self.positions = world.positions
        self.audit = world.audit

    async def __aenter__(self) -> _Uow:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def commit(self) -> None:
        return None


class _World:
    def __init__(self) -> None:
        self.entries = (
            _entry("svc-fits", "Fits"),
            _entry("svc-visit", "Visiting"),
            _entry("svc-elsewhere", "Elsewhere", status=Status.NOT_ACCEPTING),
            _entry("svc-suspended", "Alpha suspended"),
            _entry("svc-none", "Alpha none"),
        )
        self.criteria = _Criteria(
            {
                "svc-fits": _criteria("svc-fits"),
                "svc-visit": _criteria("svc-visit"),
                "svc-elsewhere": _criteria("svc-elsewhere", districts=frozenset({"DT9"})),
                "svc-suspended": _criteria("svc-suspended"),
            }
        )
        self.flags = _Flags(set(SUSPENDED))
        self.positions = _Positions(
            {"svc-fits": LatLon(50.71, -2.44), "svc-elsewhere": LatLon(50.8, -2.5)},
            {"svc-visit": ("DT2", "DT1", "DT7")},
        )
        self.audit = _Audit()

    def use_case(self) -> FindServices:
        return FindServices(
            lambda: _Uow(self),  # type: ignore[arg-type, return-value]
            _Clock(),
            _Board(self.entries),  # type: ignore[arg-type]
            _Locator(),  # type: ignore[arg-type]
            _Travel(),
        )


async def test_a_found_service_carries_its_site_position_or_none() -> None:
    result = await _World().use_case().execute(COMMAND)

    by_id = {item.service_id: item for item in result.services}
    assert by_id["svc-fits"].position == LatLon(50.71, -2.44)
    assert by_id["svc-visit"].position is None


async def test_a_visiting_service_carries_its_districts_and_the_circle_of_those_placed() -> None:
    result = await _World().use_case().execute(COMMAND)

    by_id = {item.service_id: item for item in result.services}
    visiting = by_id["svc-visit"].coverage
    assert visiting.districts == ("DT1", "DT2", "DT7")  # in name order; DT7 has no centre
    assert visiting.circle is not None
    assert visiting.circle.radius_km >= 1


async def test_a_fixed_site_covers_no_districts_and_draws_no_circle() -> None:
    result = await _World().use_case().execute(COMMAND)

    coverage = {i.service_id: i for i in result.services}["svc-fits"].coverage
    assert coverage.districts == ()
    assert coverage.circle is None


async def test_a_visiting_service_with_no_placeable_district_has_no_circle() -> None:
    world = _World()
    world.positions.covered["svc-visit"] = ("DT7",)
    result = await world.use_case().execute(COMMAND)

    coverage = {i.service_id: i for i in result.services}["svc-visit"].coverage
    assert coverage.districts == ("DT7",)
    assert coverage.circle is None


async def test_every_board_service_not_found_is_not_suitable_with_its_reasons() -> None:
    result = await _World().use_case().execute(COMMAND)

    by_id = {n.service_id: n for n in result.not_suitable}
    assert set(by_id) == {"svc-elsewhere", "svc-suspended", "svc-none"}
    assert by_id["svc-none"].reasons == (REASON_NO_CRITERIA,)
    assert by_id["svc-suspended"].reasons == (REASON_SUSPENDED,)
    assert any(r.startswith("Does not cover") for r in by_id["svc-elsewhere"].reasons)
    assert by_id["svc-elsewhere"].status is Status.NOT_ACCEPTING
    assert by_id["svc-elsewhere"].position == LatLon(50.8, -2.5)
    assert by_id["svc-none"].position is None
    assert by_id["svc-none"].category is ServiceCategory.URGENT_COMMUNITY_RESPONSE


async def test_not_suitable_is_ordered_by_name_then_id() -> None:
    world = _World()
    world.entries += (_entry("svc-a2", "Alpha none"),)
    result = await world.use_case().execute(COMMAND)

    assert [(n.name, n.service_id) for n in result.not_suitable] == [
        ("Alpha none", "svc-a2"),
        ("Alpha none", "svc-none"),
        ("Alpha suspended", "svc-suspended"),
        ("Elsewhere", "svc-elsewhere"),
    ]


async def test_found_and_not_suitable_are_disjoint_and_together_are_the_board() -> None:
    world = _World()
    result = await world.use_case().execute(COMMAND)

    found = {i.service_id for i in result.services}
    refused = {n.service_id for n in result.not_suitable}
    assert found.isdisjoint(refused)
    assert found | refused == {e.service_id for e in world.entries}
    assert len(result.services) + len(result.not_suitable) == len(world.entries)


async def test_the_found_list_is_exactly_what_match_services_returns() -> None:
    world = _World()
    kwargs: dict[str, Any] = {
        "suspended": SUSPENDED,
        "age_band": AgeBand.A80_PLUS,
        "district": DISTRICT,
        "needs": (NeedCategory.FRAILTY,),
        "now": NOW,
        "today": TODAY,
    }
    matched = match_services(world.entries, world.criteria.rows, **kwargs)
    found, refused = split_services(world.entries, world.criteria.rows, **kwargs)

    assert found == matched
    assert {i.service_id for i in found}.isdisjoint({n.service_id for n in refused})
    result = await world.use_case().execute(COMMAND)
    assert {i.service_id for i in result.services} == {i.service_id for i in matched}


async def test_only_the_boards_service_ids_are_asked_for() -> None:
    world = _World()
    await world.use_case().execute(COMMAND)

    board_ids = {e.service_id for e in world.entries}
    assert world.positions.asked
    assert all(set(asked) <= board_ids for asked in world.positions.asked)


async def test_the_audit_entry_is_unchanged_and_holds_nothing_of_the_patient_or_the_reasons(
    caplog: pytest.LogCaptureFixture,
) -> None:
    world = _World()
    with caplog.at_level(logging.DEBUG):
        await world.use_case().execute(COMMAND)

    (entry,) = world.audit.entries
    assert entry.use_case == "FindServices"
    assert entry.entity_ids == ("svc-fits", "svc-visit")
    assert entry.snapshot == {
        "services": [
            {
                "id": service_id,
                "status": "accepting",
                "figure_unavailable": False,
                "criteria_version": 4,
                "order": order,
            }
            for order, service_id in enumerate(("svc-fits", "svc-visit"), 1)
        ]
    }
    everything = (repr(entry) + caplog.text).lower()
    for value in (
        POSTCODE,
        "dt48xx",
        DISTRICT,
        "80+",
        "frailty",
        "today",
        "does not cover",
        "not currently taking",
        "no current criteria",
        "dt2",
        "50.71",
    ):
        assert value.lower() not in everything, value
