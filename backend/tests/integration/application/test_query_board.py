"""Integration tests for the QueryBoard read model (U08), against the real Neo4j the harness starts.

The board is seeded through committed units of work and read through a fresh one, so what the
tests assert is what was really stored (DEC-004). The sample services follow the "Main" artboard
in docs/spec/ui-screens.md. All values are synthetic; there is no patient data.

Clock: Friday 23 October 2026 at 14:12 London (BST, 13:12 UTC) unless a test says otherwise.
"""

import dataclasses
from datetime import UTC, datetime, time

import pytest
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.application.actor import Actor
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.query_board import (
    BoardEntry,
    QueryBoard,
    QueryBoardQuery,
)
from diucs.domain.codes import (
    BookingStatus,
    Cadence,
    Channel,
    Measure,
    ReportSource,
    ReportType,
    Role,
    ServiceCategory,
    Status,
)
from diucs.domain.errors import NotAllowed
from diucs.domain.model.booking import Booking
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.flags import SERVICE_FLAG_SUSPENDED, ServiceFlag
from diucs.domain.model.service import AvailableTime, ServiceProfile
from diucs.domain.rules.pressure import Pressure
from tests.support.neo4j import read_tx

pytestmark = pytest.mark.asyncio(loop_scope="session")

FRIDAY_NOON_LONDON = datetime(2026, 10, 23, 13, 12, tzinfo=UTC)  # 14:12 BST
FRIDAY_LATER = datetime(2026, 10, 23, 13, 25, tzinfo=UTC)  # 14:25 BST
SATURDAY_0240 = datetime(2026, 10, 24, 1, 40, tzinfo=UTC)  # 02:40 BST on Saturday

WEST_REPORT_AT = datetime(2026, 10, 23, 13, 3, tzinfo=UTC)  # 14:03 BST
EAST_REPORT_AT = datetime(2026, 10, 23, 13, 5, tzinfo=UTC)  # 14:05 BST
HOME_REPORT_AT = datetime(2026, 10, 23, 13, 0, tzinfo=UTC)  # 14:00 BST
FRAILTY_REPORT_AT = datetime(2026, 10, 23, 9, 2, tzinfo=UTC)  # 10:02 BST
FRAILTY_MISSED_DUE = datetime(2026, 10, 23, 11, 0, tzinfo=UTC)  # 12:00 BST
WEST_NEXT_DUE = datetime(2026, 10, 23, 15, 0, tzinfo=UTC)  # 16:00 BST

ACTOR = Actor(
    role=Role.ADVISOR,
    practitioner_id="prac-advisor-1",
    device_id=None,
    channel="web",
    service_ids=frozenset(),
)
ANONYMOUS = dataclasses.replace(ACTOR, role=Role.ANONYMOUS_LINK, practitioner_id=None)

UCR = ServiceCategory.URGENT_COMMUNITY_RESPONSE
HOME = ServiceCategory.HOSPITAL_AT_HOME_OR_VIRTUAL_WARD


def _ucr(service_id: str, name: str) -> ServiceProfile:
    return ServiceProfile(
        id=service_id,
        name=name,
        category=UCR,
        measure=Measure.REFERRALS_ACCEPTABLE,
        unit_label="referrals",
        established_capacity=8,
        can_exceed_established=False,
        usual_range=(0, 8),
        cadence=Cadence.EVERY_2_HRS,
        available_times=(AvailableTime.weekdays(time(8, 0), time(20, 0)),),
        channel=Channel.TEXT,
        limited_level_percent=80,
    )


WEST = _ucr("svc-ucr-west", "UCR West")
EAST = _ucr("svc-ucr-east", "UCR East")
HOME_AT_HOME = ServiceProfile(
    id="svc-hospital-at-home",
    name="Hospital at home",
    category=HOME,
    measure=Measure.OCCUPIED_PATIENTS,
    unit_label="patients",
    established_capacity=12,
    can_exceed_established=True,
    usual_range=(0, 14),
    cadence=Cadence.EVERY_2_HRS,
    available_times=(AvailableTime.every_day_all_day(),),
    channel=Channel.TEXT,
    limited_level_percent=80,
)
FRAILTY = ServiceProfile(
    id="svc-virtual-ward-frailty",
    name="Virtual ward · frailty",
    category=HOME,
    measure=Measure.FREE_BEDS,
    unit_label="beds",
    established_capacity=10,
    can_exceed_established=False,
    usual_range=(0, 10),
    cadence=Cadence.EVERY_2_HRS,
    available_times=(AvailableTime.weekdays(time(8, 0), time(20, 0)),),
    channel=Channel.TEXT,
    limited_level_percent=80,
)


def _number_report(
    report_id: str, service: ServiceProfile, value: int, at: datetime
) -> CapacityReport:
    return CapacityReport(
        id=report_id,
        service_id=service.id,
        value=value,
        measure=service.measure,
        effective_at=at,
        source=ReportSource.TEXT,
        report_type=ReportType.NUMBER,
    )


WEST_REPORT = _number_report("obs-west-1403", WEST, 4, WEST_REPORT_AT)
EAST_REPORT = _number_report("obs-east-1405", EAST, 1, EAST_REPORT_AT)
HOME_REPORT = _number_report("obs-home-1400", HOME_AT_HOME, 14, HOME_REPORT_AT)
FRAILTY_REPORT = _number_report("obs-frailty-1002", FRAILTY, 3, FRAILTY_REPORT_AT)

MAIN_PROFILES = (WEST, EAST, HOME_AT_HOME, FRAILTY)
MAIN_REPORTS = (WEST_REPORT, EAST_REPORT, HOME_REPORT, FRAILTY_REPORT)


def _limited(index: int) -> tuple[ServiceProfile, CapacityReport]:
    """A service that is limited at Friday 14:12: one of eight referrals free."""
    profile = _ucr(f"svc-limited-{index:02d}", f"Limited service {index:02d}")
    report = _number_report(f"obs-limited-{index:02d}", profile, 1, EAST_REPORT_AT)
    return profile, report


def _query(factory: UnitOfWorkFactory, at: datetime, actor: Actor = ACTOR) -> QueryBoard:
    return QueryBoard(factory, FixedClock(at))


async def _seed(
    factory: UnitOfWorkFactory,
    profiles: tuple[ServiceProfile, ...] = (),
    reports: tuple[CapacityReport, ...] = (),
    bookings: tuple[Booking, ...] = (),
    flags: tuple[ServiceFlag, ...] = (),
) -> None:
    async with factory() as uow:
        for profile in profiles:
            await uow.services.save(profile)
        for report in reports:
            await uow.capacity.add(report)
        for booking in bookings:
            await uow.bookings.add(booking)
        for flag in flags:
            await uow.flags.set_service_flag(flag)
        await uow.commit()


async def _board(
    factory: UnitOfWorkFactory, at: datetime, actor: Actor = ACTOR
) -> dict[str, BoardEntry]:
    board = await QueryBoard(factory, FixedClock(at)).execute(QueryBoardQuery(actor=actor))
    return {entry.service_id: entry for entry in board.entries}


async def _node_count(driver: AsyncDriver) -> int:
    async def count(tx: AsyncManagedTransaction) -> int:
        result = await tx.run("MATCH (n) RETURN count(n) AS nodes")
        record = await result.single()
        assert record is not None
        return int(record["nodes"])

    return await read_tx(driver, count)


async def test_ucr_west_is_accepting_with_four_available(uow_factory: UnitOfWorkFactory) -> None:
    await _seed(uow_factory, profiles=MAIN_PROFILES, reports=MAIN_REPORTS)

    west = (await _board(uow_factory, FRIDAY_NOON_LONDON))["svc-ucr-west"]

    assert west.status is Status.ACCEPTING
    assert west.effective_available == 4
    assert west.used == 4
    assert west.established == 8
    assert west.pending == 0
    assert west.over_by is None
    assert west.reported_at == WEST_REPORT_AT
    assert west.next_due_at == WEST_NEXT_DUE


async def test_ucr_east_is_limited_and_hospital_at_home_is_over_capacity(
    uow_factory: UnitOfWorkFactory,
) -> None:
    await _seed(uow_factory, profiles=MAIN_PROFILES, reports=MAIN_REPORTS)

    entries = await _board(uow_factory, FRIDAY_NOON_LONDON)

    assert entries["svc-ucr-east"].status is Status.LIMITED
    assert entries["svc-ucr-east"].effective_available == 1
    assert entries["svc-ucr-east"].used == 7
    home = entries["svc-hospital-at-home"]
    assert home.status is Status.OVER_CAPACITY
    assert home.used == 14
    assert home.over_by == 2
    assert home.effective_available is None
    assert home.established == 12


async def test_an_overdue_service_is_not_updated_with_its_missed_due_time(
    uow_factory: UnitOfWorkFactory,
) -> None:
    await _seed(uow_factory, profiles=MAIN_PROFILES, reports=MAIN_REPORTS)

    frailty = (await _board(uow_factory, FRIDAY_NOON_LONDON))["svc-virtual-ward-frailty"]

    assert frailty.status is Status.NOT_UPDATED
    assert frailty.was_due_at == FRAILTY_MISSED_DUE
    assert frailty.reported_at == FRAILTY_REPORT_AT
    assert frailty.effective_available == 3
    assert frailty.used == 7


async def test_a_requested_booking_is_pending_and_a_confirmation_takes_a_place(
    uow_factory: UnitOfWorkFactory,
) -> None:
    requested = Booking(
        id="bk-4821",
        reference="4821",
        service_id=WEST.id,
        case_id="case-4821",
        requester_id="prac-advisor-1",
        status=BookingStatus.REQUESTED,
        requested_at=datetime(2026, 10, 23, 13, 10, tzinfo=UTC),
        reply_by=datetime(2026, 10, 23, 13, 40, tzinfo=UTC),
    )
    await _seed(uow_factory, profiles=MAIN_PROFILES, reports=MAIN_REPORTS, bookings=(requested,))

    before = (await _board(uow_factory, FRIDAY_NOON_LONDON))["svc-ucr-west"]
    assert before.pending == 1
    assert before.effective_available == 4

    confirmed = requested.with_status(
        BookingStatus.CONFIRMED, datetime(2026, 10, 23, 13, 19, tzinfo=UTC)
    )
    async with uow_factory() as uow:
        await uow.bookings.save(confirmed)
        await uow.commit()

    # The confirmation is at 14:19, so the board is read at 14:25 for this step.
    after = (await _board(uow_factory, FRIDAY_LATER))["svc-ucr-west"]
    assert after.pending == 0
    assert after.effective_available == 3


async def test_a_suspended_service_is_not_updated_until_the_flag_is_lifted(
    uow_factory: UnitOfWorkFactory,
) -> None:
    flag = ServiceFlag(
        service_id=WEST.id,
        code=SERVICE_FLAG_SUSPENDED,
        active=True,
        reason="Paused for a staffing review",
        actor_id="prac-lead-1",
        at=FRIDAY_NOON_LONDON,
    )
    await _seed(uow_factory, profiles=MAIN_PROFILES, reports=MAIN_REPORTS, flags=(flag,))

    suspended = (await _board(uow_factory, FRIDAY_NOON_LONDON))["svc-ucr-west"]
    assert suspended.status is Status.NOT_UPDATED

    lifted = dataclasses.replace(flag, active=False, at=FRIDAY_LATER)
    async with uow_factory() as uow:
        await uow.flags.set_service_flag(lifted)
        await uow.commit()

    restored = (await _board(uow_factory, FRIDAY_LATER))["svc-ucr-west"]
    assert restored.status is Status.ACCEPTING


async def test_services_out_of_hours_are_left_out_of_pressure(
    uow_factory: UnitOfWorkFactory,
) -> None:
    # Five limited services would be high pressure on Friday. On Saturday at 02:40 they are closed.
    limited = [_limited(index) for index in range(5)]
    await _seed(
        uow_factory,
        profiles=tuple(profile for profile, _ in limited),
        reports=tuple(report for _, report in limited),
    )

    friday = await QueryBoard(uow_factory, FixedClock(FRIDAY_NOON_LONDON)).execute(
        QueryBoardQuery(actor=ACTOR)
    )
    saturday = await QueryBoard(uow_factory, FixedClock(SATURDAY_0240)).execute(
        QueryBoardQuery(actor=ACTOR)
    )

    assert friday.pressure is Pressure.HIGH
    assert all(entry.status is Status.OUT_OF_HOURS for entry in saturday.entries)
    assert saturday.pressure is Pressure.NORMAL
    assert saturday.all_limited_or_worse is False


@pytest.mark.parametrize(
    ("limited_count", "expected"),
    [(2, Pressure.NORMAL), (3, Pressure.WATCH), (5, Pressure.HIGH)],
)
async def test_pressure_is_normal_watch_or_high_by_count(
    uow_factory: UnitOfWorkFactory, limited_count: int, expected: Pressure
) -> None:
    limited = [_limited(index) for index in range(limited_count)]
    await _seed(
        uow_factory,
        profiles=tuple(profile for profile, _ in limited),
        reports=tuple(report for _, report in limited),
    )

    board = await QueryBoard(uow_factory, FixedClock(FRIDAY_NOON_LONDON)).execute(
        QueryBoardQuery(actor=ACTOR)
    )

    assert board.pressure is expected
    assert board.all_limited_or_worse is True


async def test_all_limited_or_worse_is_false_when_one_in_hours_service_is_accepting(
    uow_factory: UnitOfWorkFactory,
) -> None:
    limited = [_limited(index) for index in range(3)]
    await _seed(
        uow_factory,
        profiles=(WEST, *(profile for profile, _ in limited)),
        reports=(WEST_REPORT, *(report for _, report in limited)),
    )

    board = await QueryBoard(uow_factory, FixedClock(FRIDAY_NOON_LONDON)).execute(
        QueryBoardQuery(actor=ACTOR)
    )

    assert board.pressure is Pressure.WATCH
    assert board.all_limited_or_worse is False


async def test_the_anonymous_link_is_refused(uow_factory: UnitOfWorkFactory) -> None:
    await _seed(uow_factory, profiles=MAIN_PROFILES, reports=MAIN_REPORTS)

    with pytest.raises(NotAllowed):
        await QueryBoard(uow_factory, FixedClock(FRIDAY_NOON_LONDON)).execute(
            QueryBoardQuery(actor=ANONYMOUS)
        )


async def test_entries_sort_by_category_then_name(uow_factory: UnitOfWorkFactory) -> None:
    await _seed(uow_factory, profiles=MAIN_PROFILES, reports=MAIN_REPORTS)

    board = await QueryBoard(uow_factory, FixedClock(FRIDAY_NOON_LONDON)).execute(
        QueryBoardQuery(actor=ACTOR)
    )

    # Category first: "Hospital at home" (name H) follows "UCR West" (name U) because of category.
    assert [entry.name for entry in board.entries] == [
        "UCR East",
        "UCR West",
        "Hospital at home",
        "Virtual ward · frailty",
    ]


async def test_a_service_with_no_report_is_not_updated_with_no_figures(
    uow_factory: UnitOfWorkFactory,
) -> None:
    await _seed(uow_factory, profiles=(WEST,))

    west = (await _board(uow_factory, FRIDAY_NOON_LONDON))["svc-ucr-west"]

    assert west.status is Status.NOT_UPDATED
    assert west.effective_available is None
    assert west.used is None
    assert west.over_by is None
    assert west.reported_at is None


async def test_inactive_services_are_left_out(uow_factory: UnitOfWorkFactory) -> None:
    retired = dataclasses.replace(EAST, active=False)
    await _seed(uow_factory, profiles=(WEST, retired), reports=(WEST_REPORT,))

    entries = await _board(uow_factory, FRIDAY_NOON_LONDON)

    assert set(entries) == {"svc-ucr-west"}


async def test_running_the_board_leaves_the_graph_unchanged(
    neo4j_driver: AsyncDriver, uow_factory: UnitOfWorkFactory
) -> None:
    await _seed(uow_factory, profiles=MAIN_PROFILES, reports=MAIN_REPORTS)
    before = await _node_count(neo4j_driver)

    await QueryBoard(uow_factory, FixedClock(FRIDAY_NOON_LONDON)).execute(
        QueryBoardQuery(actor=ACTOR)
    )

    assert await _node_count(neo4j_driver) == before


async def test_a_board_entry_holds_only_service_fields() -> None:
    # No field can hold a patient name, NHS number, postcode or free text about a patient.
    assert {field.name for field in dataclasses.fields(BoardEntry)} == {
        "service_id",
        "name",
        "category",
        "status",
        "effective_available",
        "over_by",
        "used",
        "established",
        "pending",
        "unit_label",
        "comment",
        "reported_at",
        "next_due_at",
        "was_due_at",
    }


async def test_bookings_count_only_for_their_own_service(uow_factory: UnitOfWorkFactory) -> None:
    west_request = Booking(
        id="bk-4821",
        reference="4821",
        service_id=WEST.id,
        case_id="case-4821",
        requester_id="prac-advisor-1",
        status=BookingStatus.REQUESTED,
        requested_at=datetime(2026, 10, 23, 13, 10, tzinfo=UTC),
        reply_by=datetime(2026, 10, 23, 13, 40, tzinfo=UTC),
    )
    east_request = dataclasses.replace(
        west_request, id="bk-4822", reference="4822", service_id=EAST.id
    )
    await _seed(
        uow_factory,
        profiles=MAIN_PROFILES,
        reports=MAIN_REPORTS,
        bookings=(west_request, east_request),
    )
    async with uow_factory() as uow:
        await uow.bookings.save(
            east_request.with_status(
                BookingStatus.CONFIRMED, datetime(2026, 10, 23, 13, 19, tzinfo=UTC)
            )
        )
        await uow.commit()

    entries = await _board(uow_factory, FRIDAY_LATER)

    # Each service counts only its own bookings: UCR West keeps its pending request, and the
    # confirmed UCR East booking takes its last place without changing UCR West.
    assert entries["svc-ucr-west"].pending == 1
    assert entries["svc-ucr-west"].effective_available == 4
    assert entries["svc-ucr-east"].pending == 0
    assert entries["svc-ucr-east"].effective_available == 0
    assert entries["svc-hospital-at-home"].pending == 0
    assert entries["svc-virtual-ward-frailty"].pending == 0
