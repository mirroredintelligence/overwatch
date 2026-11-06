"""The duty roster against the real graph (DEC-1341): who is on a service's roster, who is on shift,
who is sent a prompt, and the newest check-in replacing the last. Sample values only."""

from dataclasses import replace
from datetime import UTC, datetime, time, timedelta

import pytest
from neo4j import AsyncDriver

from overwatch.adapters.outbound.audit_neo4j.audit_log import ensure_audit_head
from overwatch.adapters.testing.fixed_clock import FixedClock
from overwatch.adapters.testing.fixed_ids import SequentialIds
from overwatch.adapters.testing.fixed_secrets import FixedSecretStore
from overwatch.application.actor import Actor
from overwatch.application.ports.outbound.identity import (
    PHONE_HASH_SECRET,
    HmacPhoneHasher,
    normalise_uk_mobile,
)
from overwatch.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from overwatch.application.use_cases.duty_roster import (
    AddRosterManager,
    AddRosterManagerCommand,
    CheckIn,
    ListRoster,
    RemoveRosterManager,
    SignOff,
)
from overwatch.application.use_cases.query_board import QueryBoard, QueryBoardQuery
from overwatch.domain.codes import (
    Cadence,
    Channel,
    Measure,
    PractitionerRoleCode,
    ReportSource,
    ReportType,
    Role,
    ServiceCategory,
    Status,
)
from overwatch.domain.errors import Conflict, NotAllowed, ValidationFailed
from overwatch.domain.model.capacity import CapacityReport
from overwatch.domain.model.people import Practitioner, PractitionerRole, RosterState
from overwatch.domain.model.service import AvailableTime, ServiceProfile
from tests.integration.application.conftest import Seed
from tests.support.actors import ACTOR_TENANT

pytestmark = pytest.mark.asyncio(loop_scope="session")

NOW = datetime(2026, 11, 6, 10, 0, tzinfo=UTC)
SECRETS = FixedSecretStore({PHONE_HASH_SECRET: b"phone-hash-test-secret-0123456789ab"})
HASHER = HmacPhoneHasher(SECRETS)
ANA = "07700 900111"
BEN = "07700 900222"
LEAD = Actor(
    role=Role.LEAD,
    practitioner_id="prac-lead",
    device_id=None,
    channel="web",
    service_ids=frozenset(),
    tenant_id=ACTOR_TENANT,
)
SERVICE = ServiceProfile(
    id="ucr-west",
    name="UCR West",
    category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
    measure=Measure.REFERRALS_ACCEPTABLE,
    unit_label="referrals in the next 2 hrs",
    established_capacity=8,
    can_exceed_established=False,
    usual_range=(0, 8),
    cadence=Cadence.EVERY_2_HRS,
    available_times=(AvailableTime.every_day(time(8, 0), time(20, 0)),),
    channel=Channel.TEXT,
    limited_level_percent=80,
)
OTHER = replace(SERVICE, id="ucr-east", name="UCR East")


class Rig:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self.uow_factory = uow_factory
        self.clock = FixedClock(NOW)
        ids = SequentialIds("ros")
        self.add = AddRosterManager(uow_factory, self.clock, ids, HASHER)
        self.remove = RemoveRosterManager(uow_factory, self.clock)
        self.list = ListRoster(uow_factory, self.clock)
        self.check_in = CheckIn(uow_factory, self.clock, ids)
        self.sign_off = SignOff(uow_factory, self.clock)

    async def add_person(self, name: str, mobile: str, service: str = "ucr-west") -> str:
        result = await self.add.execute(AddRosterManagerCommand(LEAD, service, name, mobile))
        return result.role_id

    async def states(self, service: str = "ucr-west") -> dict[str, RosterState]:
        return {entry.name: entry.state for entry in await self.list.execute(LEAD, service)}

    async def reporters(self, service: str = "ucr-west") -> list[PractitionerRole]:
        async with self.uow_factory() as uow:
            return await uow.people.reporter_roles_for_service(service, self.clock.now())


@pytest.fixture
async def rig(
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    clean_graph: None,
    seed_service: Seed,
) -> Rig:
    await ensure_audit_head(neo4j_driver)
    await seed_service(SERVICE, OTHER)
    async with uow_factory() as uow:
        await uow.people.save_practitioner(
            Practitioner(id="prac-lead", active=True, display_name="Shift lead", phone_hash=None)
        )
        await uow.commit()
    return Rig(uow_factory)


def _hash(mobile: str) -> str:
    return HASHER.hash(normalise_uk_mobile(mobile))


async def test_a_person_added_to_the_roster_is_off_shift_and_is_sent_no_prompt(rig: Rig) -> None:
    await rig.add_person("Ana Duty", ANA)

    assert await rig.states() == {"Ana Duty": RosterState.OFF_SHIFT}
    assert await rig.reporters() == []
    entries = await rig.list.execute(LEAD, "ucr-west")
    assert entries[0].number_ending == "0111"
    assert entries[0].shift_end is None


async def test_the_same_person_cannot_be_added_to_a_service_twice(rig: Rig) -> None:
    await rig.add_person("Ana Duty", ANA)
    with pytest.raises(Conflict):
        await rig.add_person("Ana D", ANA)


async def test_a_person_can_be_on_the_roster_of_two_services(rig: Rig) -> None:
    await rig.add_person("Ana Duty", ANA)
    await rig.add_person("Ana Duty", ANA, service="ucr-east")

    assert await rig.states("ucr-east") == {"Ana Duty": RosterState.OFF_SHIFT}


async def test_only_a_shift_lead_may_add_remove_or_list(rig: Rig) -> None:
    advisor = replace(LEAD, role=Role.ADVISOR)
    with pytest.raises(NotAllowed):
        await rig.add.execute(AddRosterManagerCommand(advisor, "ucr-west", "Ana Duty", ANA))
    with pytest.raises(NotAllowed):
        await rig.list.execute(advisor, "ucr-west")


async def test_a_name_that_is_too_short_or_not_a_name_is_refused(rig: Rig) -> None:
    with pytest.raises(ValidationFailed):
        await rig.add_person("A", ANA)
    with pytest.raises(ValidationFailed):
        await rig.add_person("Ana Duty", "not a number")


async def test_checking_in_puts_the_person_on_shift_for_eight_hours_by_default(rig: Rig) -> None:
    await rig.add_person("Ana Duty", ANA)

    changes = await rig.check_in.execute(_hash(ANA), None, LEAD)

    assert [(change.service_name, change.shift_end) for change in changes] == [
        ("UCR West", NOW + timedelta(hours=8))
    ]
    assert await rig.states() == {"Ana Duty": RosterState.ON_SHIFT}
    [role] = await rig.reporters()
    assert role.service_id == "ucr-west"


async def test_a_shift_cannot_be_longer_than_fourteen_hours_or_shorter_than_one(rig: Rig) -> None:
    await rig.add_person("Ana Duty", ANA)
    for hours in (0, 15):
        with pytest.raises(ValidationFailed):
            await rig.check_in.execute(_hash(ANA), hours, LEAD)
    assert await rig.states() == {"Ana Duty": RosterState.OFF_SHIFT}


async def test_the_newest_check_in_replaces_the_last(rig: Rig) -> None:
    await rig.add_person("Ana Duty", ANA)
    await rig.add_person("Ben Duty", BEN)
    await rig.check_in.execute(_hash(ANA), 8, LEAD)

    await rig.check_in.execute(_hash(BEN), 4, LEAD)

    assert await rig.states() == {
        "Ana Duty": RosterState.OFF_SHIFT,
        "Ben Duty": RosterState.ON_SHIFT,
    }
    [role] = await rig.reporters()
    entries = {entry.role_id: entry for entry in await rig.list.execute(LEAD, "ucr-west")}
    assert entries[role.id].name == "Ben Duty"


async def test_signing_off_puts_the_person_off_shift_and_stops_their_prompts(rig: Rig) -> None:
    await rig.add_person("Ana Duty", ANA)
    await rig.check_in.execute(_hash(ANA), 8, LEAD)

    changes = await rig.sign_off.execute(_hash(ANA), LEAD)

    assert [change.service_name for change in changes] == ["UCR West"]
    assert await rig.states() == {"Ana Duty": RosterState.OFF_SHIFT}
    assert await rig.reporters() == []


async def test_signing_off_when_not_on_shift_changes_nothing(rig: Rig) -> None:
    await rig.add_person("Ana Duty", ANA)
    assert await rig.sign_off.execute(_hash(ANA), LEAD) == []


async def test_a_shift_that_has_ended_is_off_shift_and_sends_no_prompt(rig: Rig) -> None:
    await rig.add_person("Ana Duty", ANA)
    await rig.check_in.execute(_hash(ANA), 2, LEAD)

    rig.clock.set(NOW + timedelta(hours=2, minutes=1))

    assert await rig.states() == {"Ana Duty": RosterState.OFF_SHIFT}
    assert await rig.reporters() == []


async def test_a_number_that_is_not_on_any_roster_checks_in_nowhere(rig: Rig) -> None:
    await rig.add_person("Ana Duty", ANA)
    assert await rig.check_in.execute(_hash(BEN), 8, LEAD) == []


async def test_checking_in_goes_on_shift_for_every_service_the_person_is_on(rig: Rig) -> None:
    await rig.add_person("Ana Duty", ANA)
    await rig.add_person("Ana Duty", ANA, service="ucr-east")

    changes = await rig.check_in.execute(_hash(ANA), 6, LEAD)

    assert sorted(change.service_name for change in changes) == ["UCR East", "UCR West"]
    assert await rig.states("ucr-east") == {"Ana Duty": RosterState.ON_SHIFT}


async def test_a_removed_person_leaves_the_roster_and_can_no_longer_check_in(rig: Rig) -> None:
    role_id = await rig.add_person("Ana Duty", ANA)

    await rig.remove.execute(LEAD, role_id)

    assert await rig.states() == {}
    assert await rig.check_in.execute(_hash(ANA), 8, LEAD) == []


async def test_a_removed_person_can_be_added_again(rig: Rig) -> None:
    role_id = await rig.add_person("Ana Duty", ANA)
    await rig.remove.execute(LEAD, role_id)

    await rig.add_person("Ana Duty", ANA)

    assert await rig.states() == {"Ana Duty": RosterState.OFF_SHIFT}


# --- the board when nobody is on shift (DEC-1341 item 6) ---------------------------


async def _report(rig: Rig, service: str = "ucr-west", minutes_ago: int = 10) -> None:
    async with rig.uow_factory() as uow:
        await uow.capacity.add(
            CapacityReport(
                id=f"obs-{service}-{int(rig.clock.now().timestamp())}",
                service_id=service,
                value=4,
                measure=Measure.REFERRALS_ACCEPTABLE,
                effective_at=rig.clock.now() - timedelta(minutes=minutes_ago),
                source=ReportSource.TEXT,
                report_type=ReportType.NUMBER,
            )
        )
        await uow.commit()


async def _board_status(rig: Rig, service: str = "ucr-west") -> Status:
    board = await QueryBoard(rig.uow_factory, rig.clock).execute(QueryBoardQuery(LEAD))
    return next(entry.status for entry in board.entries if entry.service_id == service)


async def test_a_rostered_service_with_nobody_ever_on_shift_is_stale_on_the_board(rig: Rig) -> None:
    await rig.add_person("Ana Duty", ANA)
    await _report(rig)

    assert await _board_status(rig) is Status.NOT_UPDATED


async def test_a_rostered_service_with_someone_on_shift_shows_its_figure(rig: Rig) -> None:
    await rig.add_person("Ana Duty", ANA)
    await _report(rig)
    await rig.check_in.execute(_hash(ANA), 8, LEAD)

    assert await _board_status(rig) is not Status.NOT_UPDATED


async def test_a_service_stays_as_it_was_for_fifteen_minutes_after_the_last_shift_ends(
    rig: Rig,
) -> None:
    await rig.add_person("Ana Duty", ANA)
    await _report(rig)
    await rig.check_in.execute(_hash(ANA), 2, LEAD)

    rig.clock.set(NOW + timedelta(hours=2, minutes=14))
    await _report(rig, minutes_ago=1)
    inside = await _board_status(rig)
    rig.clock.set(NOW + timedelta(hours=2, minutes=16))
    await _report(rig, minutes_ago=1)
    outside = await _board_status(rig)

    assert inside is not Status.NOT_UPDATED
    assert outside is Status.NOT_UPDATED


async def test_signing_off_starts_the_same_fifteen_minutes(rig: Rig) -> None:
    await rig.add_person("Ana Duty", ANA)
    await _report(rig)
    await rig.check_in.execute(_hash(ANA), 8, LEAD)
    await rig.sign_off.execute(_hash(ANA), LEAD)

    inside = await _board_status(rig)
    rig.clock.set(NOW + timedelta(minutes=16))
    outside = await _board_status(rig)

    assert inside is not Status.NOT_UPDATED
    assert outside is Status.NOT_UPDATED


async def test_the_next_person_going_on_shift_makes_the_figure_current_again(rig: Rig) -> None:
    await rig.add_person("Ana Duty", ANA)
    await rig.add_person("Ben Duty", BEN)
    await _report(rig)
    await rig.check_in.execute(_hash(ANA), 2, LEAD)
    rig.clock.set(NOW + timedelta(hours=3))
    await _report(rig, minutes_ago=1)
    assert await _board_status(rig) is Status.NOT_UPDATED

    await rig.check_in.execute(_hash(BEN), 4, LEAD)

    assert await _board_status(rig) is not Status.NOT_UPDATED


async def test_a_service_with_an_always_on_reporter_is_never_stale_for_want_of_a_roster_shift(
    rig: Rig,
) -> None:
    await rig.add_person("Ana Duty", ANA)
    await _report(rig)
    async with rig.uow_factory() as uow:
        await uow.people.save_practitioner(
            Practitioner(id="prac-rep", active=True, display_name="Duty manager", phone_hash=None)
        )
        await uow.people.save_role(
            PractitionerRole(
                id="role-rep",
                practitioner_id="prac-rep",
                service_id="ucr-west",
                code=PractitionerRoleCode.DUTY_MANAGER,
                active=True,
                channel=Channel.TEXT,
                period_start=NOW - timedelta(days=1),
            )
        )
        await uow.commit()

    assert await _board_status(rig) is not Status.NOT_UPDATED


async def test_a_service_with_no_roster_is_not_changed(rig: Rig) -> None:
    await _report(rig)
    assert await _board_status(rig) is not Status.NOT_UPDATED


async def test_a_closed_service_is_shown_closed_not_stale(rig: Rig) -> None:
    await rig.add_person("Ana Duty", ANA)
    await _report(rig)
    rig.clock.set(datetime(2026, 11, 6, 22, 0, tzinfo=UTC))

    assert await _board_status(rig) is Status.OUT_OF_HOURS
