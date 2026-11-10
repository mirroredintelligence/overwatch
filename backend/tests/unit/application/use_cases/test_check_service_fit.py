"""CheckServiceFit (DEC-1377): does one service take this patient, by the find rule. Pure: fakes for
the board and the unit of work. Browse only: the audit entry holds the service id, the result and
the criteria version, never the postcode, district, age band, needs or urgency. Samples only."""

import logging
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from overwatch.application.actor import Actor
from overwatch.application.use_cases.find_services import (
    REASON_NO_CRITERIA,
    REASON_SUSPENDED,
    CheckServiceFit,
    CheckServiceFitCommand,
    match_services,
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
from overwatch.domain.errors import NotAllowed, NotFound, ValidationFailed
from overwatch.domain.model.criteria import ServiceCriteria
from overwatch.domain.rules.pressure import Pressure

NOW = datetime(2026, 11, 10, 14, 0, tzinfo=UTC)
POSTCODE = "DT4 8XX"
DISTRICT = "DT4"
SERVICE = "svc-a"


def _entry(**changes: object) -> BoardEntry:
    base = BoardEntry(
        service_id=SERVICE,
        name="Alpha",
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


def _criteria(**changes: object) -> ServiceCriteria:
    base = ServiceCriteria(
        id="crit-1",
        service_id=SERVICE,
        version=3,
        status=CriteriaStatus.CURRENT,
        age_min=16,
        age_max=None,
        districts=frozenset({"DT1", DISTRICT}),
        accepts=frozenset({NeedCategory.FRAILTY, NeedCategory.FALL_NO_INJURY}),
        excludes=frozenset(),
        review_by=date(2026, 12, 31),
        owner_role_id="role-lead",
    )
    return replace(base, **changes)  # type: ignore[arg-type]


def _actor(role: Role = Role.ADVISOR_V2) -> Actor:
    return Actor(
        role=role,
        practitioner_id=None,
        device_id=None,
        channel="app",
        service_ids=frozenset(),
        tenant_id="tenant-a",
    )


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
        self._rows = rows
        self.asked: list[list[str]] = []

    async def current_for_services(self, ids: list[str]) -> dict[str, ServiceCriteria]:
        self.asked.append(list(ids))
        return {i: self._rows[i] for i in ids if i in self._rows}


class _Flags:
    def __init__(self, suspended: set[str]) -> None:
        self._suspended = suspended

    async def services_with_flag(self, code: str) -> set[str]:
        return self._suspended


class _Services:
    async def work_phones(self, ids: list[str]) -> dict[str, str]:
        return {SERVICE: "01305 000111"}


class _Uow:
    def __init__(self, world: _World) -> None:
        self.criteria = world.criteria
        self.flags = world.flags
        self.services = _Services()
        self.audit = world.audit
        world.opened += 1

    async def __aenter__(self) -> _Uow:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def commit(self) -> None:
        return None


class _World:
    def __init__(
        self,
        *,
        entries: tuple[BoardEntry, ...] = (_entry(),),
        criteria: dict[str, ServiceCriteria] | None = None,
        suspended: set[str] | None = None,
    ) -> None:
        self.entries = entries
        self.criteria = _Criteria({SERVICE: _criteria()} if criteria is None else criteria)
        self.flags = _Flags(suspended or set())
        self.audit = _Audit()
        self.opened = 0

    def use_case(self) -> CheckServiceFit:
        return CheckServiceFit(
            lambda: _Uow(self),  # type: ignore[arg-type, return-value]
            _Clock(),
            _Board(self.entries),  # type: ignore[arg-type]
        )


def _command(**changes: object) -> CheckServiceFitCommand:
    base = CheckServiceFitCommand(
        actor=_actor(),
        service_id=SERVICE,
        postcode=POSTCODE,
        age_band=AgeBand.A80_PLUS,
        needs=(NeedCategory.FRAILTY,),
        urgency=Urgency.TODAY,
    )
    return replace(base, **changes)  # type: ignore[arg-type]


async def test_a_service_that_takes_the_patient_fits_with_its_lines_phone_and_status() -> None:
    result = await _World().use_case().execute(_command())

    assert result.fits is True
    assert result.reasons == ()
    assert "Takes frailty" in " ".join(result.fits_needs)
    assert (result.phone, result.status, result.figure_unavailable) == (
        "01305 000111",
        Status.ACCEPTING,
        False,
    )
    assert result.service_id == SERVICE


async def test_a_service_outside_the_criteria_does_not_fit_and_gives_the_reasons() -> None:
    world = _World(criteria={SERVICE: _criteria(districts=frozenset({"DT9"}))})
    result = await world.use_case().execute(_command(needs=(NeedCategory.WOUND_CARE,)))

    assert result.fits is False
    assert any("Does not cover" in reason for reason in result.reasons)
    assert any("wound-care" in reason for reason in result.reasons)
    assert result.fits_needs == ()


async def test_the_answer_is_the_find_answer_for_the_same_service() -> None:
    entry, criteria = _entry(status=Status.LIMITED), _criteria()
    found = match_services(
        (entry,),
        {SERVICE: criteria},
        suspended=set(),
        age_band=AgeBand.A80_PLUS,
        district=DISTRICT,
        needs=(NeedCategory.FRAILTY,),
        now=NOW,
        today=date(2026, 11, 10),
        phones={SERVICE: "01305 000111"},
    )[0]
    result = await _World(entries=(entry,)).use_case().execute(_command())

    assert (result.fits_needs, result.warnings, result.phone, result.status) == (
        found.fits,
        found.warnings,
        found.phone,
        found.status,
    )
    assert result.figure_unavailable == found.figure_unavailable
    assert result.warnings  # the limited warning


async def test_the_warnings_come_back_when_it_does_not_fit_too() -> None:
    world = _World(
        entries=(_entry(status=Status.OVER_CAPACITY, reported_at=NOW - timedelta(days=2)),),
        criteria={SERVICE: _criteria(districts=frozenset({"DT9"}), review_by=date(2026, 1, 1))},
    )
    result = await world.use_case().execute(_command())

    assert result.fits is False
    assert len(result.warnings) >= 3
    assert result.figure_unavailable is True


async def test_a_suspended_service_never_fits() -> None:
    result = await _World(suspended={SERVICE}).use_case().execute(_command())

    assert (result.fits, result.reasons, result.fits_needs) == (False, (REASON_SUSPENDED,), ())
    assert REASON_SUSPENDED == "Not currently taking referrals"


async def test_a_service_with_no_current_criteria_never_fits() -> None:
    result = await _World(criteria={}).use_case().execute(_command())

    assert (result.fits, result.reasons, result.fits_needs) == (False, (REASON_NO_CRITERIA,), ())
    assert REASON_NO_CRITERIA == "No current criteria"


async def test_only_that_services_criteria_are_read() -> None:
    world = _World()
    await world.use_case().execute(_command())

    assert world.criteria.asked == [[SERVICE]]


async def test_a_service_that_is_not_on_the_tenants_board_is_not_found() -> None:
    with pytest.raises(NotFound):
        await _World().use_case().execute(_command(service_id="svc-other-tenant"))


@pytest.mark.parametrize("role", [Role.ADVISOR, Role.ADVISOR_V2])
async def test_the_advisor_and_advisor_v2_may_check(role: Role) -> None:
    result = await _World().use_case().execute(_command(actor=_actor(role)))
    assert result.fits is True


@pytest.mark.parametrize("role", [r for r in Role if r not in (Role.ADVISOR, Role.ADVISOR_V2)])
async def test_every_other_role_is_refused_before_anything_is_read(role: Role) -> None:
    world = _World()
    with pytest.raises(NotAllowed):
        await world.use_case().execute(_command(actor=_actor(role)))
    assert world.opened == 0


async def test_a_postcode_that_is_not_full_is_refused_without_echoing_it() -> None:
    with pytest.raises(ValidationFailed) as refused:
        await _World().use_case().execute(_command(postcode="hello-there"))
    assert "hello-there" not in str(refused.value)


@pytest.mark.parametrize("suspended", [False, True])
async def test_the_audit_entry_holds_only_the_service_the_result_and_the_version(
    suspended: bool, caplog: pytest.LogCaptureFixture
) -> None:
    world = _World(suspended={SERVICE} if suspended else set())
    with caplog.at_level(logging.DEBUG):
        await world.use_case().execute(_command())

    (entry,) = world.audit.entries
    assert (entry.action, entry.use_case, entry.entity_ids) == ("R", "CheckServiceFit", (SERVICE,))
    assert entry.snapshot == {"service_id": SERVICE, "fits": not suspended, "criteria_version": 3}
    assert entry.actor.role is Role.ADVISOR_V2
    everything = (repr(entry) + caplog.text).lower()
    for value in (POSTCODE, "dt48xx", DISTRICT, "80+", "frailty", "today"):
        assert value.lower() not in everything, value


async def test_a_service_with_no_criteria_is_audited_with_no_version() -> None:
    world = _World(criteria={})
    await world.use_case().execute(_command())

    assert world.audit.entries[0].snapshot == {
        "service_id": SERVICE,
        "fits": False,
        "criteria_version": None,
    }
