"""The texts 15 minutes before and after a duty manager's shift ends (DEC-1341 item 4), against the
real graph: the two jobs a check-in schedules, the text each sends, and the cases where a job
must say nothing (the shift was extended, signed off, replaced or removed). Sample values only."""

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
    RemoveRosterManager,
    SignOff,
)
from overwatch.application.use_cases.shift_notices import SendShiftNotice
from overwatch.application.work import CANCELLED, SCHEDULED, ScheduledWork, WorkKind
from overwatch.domain.codes import Cadence, Channel, Measure, Role, ServiceCategory
from overwatch.domain.model.people import Practitioner
from overwatch.domain.model.service import AvailableTime, ServiceProfile
from tests.integration.application.conftest import Seed
from tests.support.actors import ACTOR_TENANT
from tests.support.sealing import TEST_SEALER, text_of
from tests.support.zones import FixedZones

pytestmark = pytest.mark.asyncio(loop_scope="session")

NOW = datetime(2026, 11, 6, 10, 0, tzinfo=UTC)
HASHER = HmacPhoneHasher(
    FixedSecretStore({PHONE_HASH_SECRET: b"phone-hash-test-secret-0123456789ab"})
)
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
WEST = ServiceProfile(
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
EAST = replace(WEST, id="ucr-east", name="UCR East")


def _hash(mobile: str) -> str:
    return HASHER.hash(normalise_uk_mobile(mobile))


class Rig:
    def __init__(self, factory: UnitOfWorkFactory, zones: FixedZones | None = None) -> None:
        self.factory = factory
        self.clock = FixedClock(NOW)
        ids = SequentialIds("sn")
        self.add = AddRosterManager(factory, self.clock, ids, HASHER)
        self.check_in = CheckIn(factory, self.clock, ids)
        self.sign_off = SignOff(factory, self.clock)
        self.remove = RemoveRosterManager(factory, self.clock)
        self.notice = SendShiftNotice(factory, self.clock, SequentialIds("nt"), TEST_SEALER, zones)

    async def person(self, name: str, mobile: str, service: str = "ucr-west") -> str:
        result = await self.add.execute(AddRosterManagerCommand(LEAD, service, name, mobile))
        return result.role_id

    async def works(self, role_id: str) -> list[ScheduledWork]:
        async with self.factory() as uow:
            return sorted(await uow.scheduled_work.for_about(role_id), key=lambda w: w.due_at)

    async def run(self, work: ScheduledWork) -> None:
        """Run a job at its own due time, as the scheduler does."""
        self.clock.set(work.due_at)
        await self.notice.execute(work)

    async def sent(self) -> list[str]:
        async with self.factory() as uow:
            pending = await uow.outbox.pending(1000)
        return [
            text_of(message, ACTOR_TENANT)
            for message in pending
            if message.event_type == "SendMessage"
        ]


@pytest.fixture
async def rig(
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    clean_graph: None,
    seed_service: Seed,
) -> Rig:
    await ensure_audit_head(neo4j_driver)
    await seed_service(WEST, EAST)
    async with uow_factory() as uow:
        await uow.people.save_practitioner(
            Practitioner(id="prac-lead", active=True, display_name="Shift lead", phone_hash=None)
        )
        await uow.commit()
    return Rig(uow_factory)


async def test_checking_in_schedules_a_text_15_minutes_before_the_end_and_one_15_minutes_after(
    rig: Rig,
) -> None:
    role = await rig.person("Ana Duty", ANA)

    await rig.check_in.execute(_hash(ANA), 8, LEAD)

    works = await rig.works(role)
    assert [(w.kind, w.due_at, w.status) for w in works] == [
        (WorkKind.SHIFT_ENDING, NOW + timedelta(hours=7, minutes=45), SCHEDULED),
        (WorkKind.SHIFT_ENDED, NOW + timedelta(hours=8, minutes=15), SCHEDULED),
    ]


async def test_the_text_before_the_end_says_when_the_shift_ends_and_how_to_carry_on_or_finish(
    rig: Rig,
) -> None:
    role = await rig.person("Ana Duty", ANA)
    await rig.check_in.execute(_hash(ANA), 8, LEAD)
    before, _ = await rig.works(role)

    await rig.run(before)

    assert await rig.sent() == [
        "Overwatch: your shift for UCR West ends at 18:00. Reply OFF if you have finished, "
        "or ON to carry on."
    ]


async def test_the_text_after_the_end_says_the_shift_ended_and_asks_if_they_are_still_on(
    rig: Rig,
) -> None:
    role = await rig.person("Ana Duty", ANA)
    await rig.check_in.execute(_hash(ANA), 8, LEAD)
    _, after = await rig.works(role)

    await rig.run(after)

    assert await rig.sent() == [
        "Overwatch: your shift for UCR West ended at 18:00. Reply ON if you are still on shift."
    ]


async def test_a_shift_that_was_extended_has_its_old_jobs_cancelled_and_new_ones(rig: Rig) -> None:
    role = await rig.person("Ana Duty", ANA)
    await rig.check_in.execute(_hash(ANA), 4, LEAD)
    old = await rig.works(role)

    await rig.check_in.execute(_hash(ANA), 8, LEAD)

    works = await rig.works(role)
    assert [w.status for w in works if w.id in {o.id for o in old}] == [CANCELLED, CANCELLED]
    assert sorted(w.due_at for w in works if w.status == SCHEDULED) == [
        NOW + timedelta(hours=7, minutes=45),
        NOW + timedelta(hours=8, minutes=15),
    ]


async def test_an_old_job_that_runs_anyway_after_the_shift_changed_sends_nothing(rig: Rig) -> None:
    role = await rig.person("Ana Duty", ANA)
    await rig.check_in.execute(_hash(ANA), 4, LEAD)
    old_before, _ = await rig.works(role)
    await rig.check_in.execute(_hash(ANA), 8, LEAD)

    await rig.run(old_before)

    assert await rig.sent() == []


async def test_signing_off_cancels_the_jobs(rig: Rig) -> None:
    role = await rig.person("Ana Duty", ANA)
    await rig.check_in.execute(_hash(ANA), 8, LEAD)
    await rig.sign_off.execute(_hash(ANA), LEAD)

    works = await rig.works(role)

    assert [w.status for w in works] == [CANCELLED, CANCELLED]
    await rig.run(works[0])
    assert await rig.sent() == []


async def test_the_next_person_going_on_shift_cancels_the_last_persons_jobs(rig: Rig) -> None:
    ana = await rig.person("Ana Duty", ANA)
    await rig.person("Ben Duty", BEN)
    await rig.check_in.execute(_hash(ANA), 8, LEAD)

    await rig.check_in.execute(_hash(BEN), 8, LEAD)

    assert [w.status for w in await rig.works(ana)] == [CANCELLED, CANCELLED]


async def test_removing_a_person_cancels_their_jobs(rig: Rig) -> None:
    role = await rig.person("Ana Duty", ANA)
    await rig.check_in.execute(_hash(ANA), 8, LEAD)

    await rig.remove.execute(LEAD, role)

    assert [w.status for w in await rig.works(role)] == [CANCELLED, CANCELLED]


async def test_a_person_on_two_services_is_told_once_naming_both(rig: Rig) -> None:
    west = await rig.person("Ana Duty", ANA)
    east = await rig.person("Ana Duty", ANA, service="ucr-east")
    await rig.check_in.execute(_hash(ANA), 8, LEAD)
    west_before = (await rig.works(west))[0]
    east_before = (await rig.works(east))[0]

    await rig.run(west_before)
    await rig.run(east_before)

    assert await rig.sent() == [
        "Overwatch: your shift for UCR East and UCR West ends at 18:00. Reply OFF if you have "
        "finished, or ON to carry on."
    ]


async def test_the_text_before_the_end_is_not_sent_once_the_end_has_passed(rig: Rig) -> None:
    role = await rig.person("Ana Duty", ANA)
    await rig.check_in.execute(_hash(ANA), 8, LEAD)
    before, _ = await rig.works(role)
    rig.clock.set(NOW + timedelta(hours=8, minutes=1))

    await rig.notice.execute(before)

    assert await rig.sent() == []


async def test_the_text_after_the_end_is_not_sent_before_the_end(rig: Rig) -> None:
    role = await rig.person("Ana Duty", ANA)
    await rig.check_in.execute(_hash(ANA), 8, LEAD)
    _, after = await rig.works(role)
    rig.clock.set(NOW + timedelta(hours=7))

    await rig.notice.execute(after)

    assert await rig.sent() == []


async def test_the_same_job_run_twice_tells_the_person_once(rig: Rig) -> None:
    role = await rig.person("Ana Duty", ANA)
    await rig.check_in.execute(_hash(ANA), 8, LEAD)
    before, _ = await rig.works(role)

    await rig.run(before)
    await rig.run(before)

    assert len(await rig.sent()) == 1


async def test_both_texts_name_the_end_in_the_tenants_zone_not_in_london(
    uow_factory: UnitOfWorkFactory, rig: Rig
) -> None:
    """18:00 in London in November is 13:00 in New York."""
    zones = FixedZones()
    local = Rig(uow_factory, zones)
    role = await local.person("Ana Duty", ANA)
    await local.check_in.execute(_hash(ANA), 8, LEAD)
    before, after = await local.works(role)

    await local.run(before)
    await local.run(after)

    assert await local.sent() == [
        "Overwatch: your shift for UCR West ends at 13:00. Reply OFF if you have finished, "
        "or ON to carry on.",
        "Overwatch: your shift for UCR West ended at 13:00. Reply ON if you are still on shift.",
    ]
    assert zones.asked and all(scope.value == ACTOR_TENANT for scope in zones.asked)
