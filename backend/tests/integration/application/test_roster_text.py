"""ON and OFF by text (DEC-1341): the reply handler and the roster together on the real graph.

A person on a service's roster texts ON to go on shift and OFF to go off, is told so in a sealed
text, and while on shift is sent the prompts. A phone on no roster is not read here. Sample values
only."""

import json
from dataclasses import replace
from datetime import UTC, datetime, time

import pytest
from neo4j import AsyncDriver

from overwatch.adapters.outbound.audit_neo4j.audit_log import ensure_audit_head
from overwatch.adapters.outbound.graph_store.idempotency_store import DriverIdempotencyStore
from overwatch.adapters.testing.fixed_clock import FixedClock
from overwatch.adapters.testing.fixed_ids import SequentialIds
from overwatch.adapters.testing.fixed_secrets import FixedSecretStore
from overwatch.adapters.testing.memory_cache import InMemoryCache
from overwatch.application.actor import Actor
from overwatch.application.ports.outbound.identity import (
    PHONE_HASH_SECRET,
    HmacPhoneHasher,
    normalise_uk_mobile,
)
from overwatch.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from overwatch.application.use_cases.confirm_capacity import ConfirmCapacity
from overwatch.application.use_cases.duty_roster import (
    AddRosterManager,
    AddRosterManagerCommand,
    CheckIn,
    ListRoster,
    SignOff,
)
from overwatch.application.use_cases.handle_inbound_text import (
    ROSTER_NOT_ON,
    ROSTER_OFF,
    ROSTER_ON,
    HandleInboundText,
    HandleInboundTextCommand,
)
from overwatch.application.use_cases.report_capacity import ReportCapacity
from overwatch.domain.codes import Cadence, Channel, Measure, Role, ServiceCategory
from overwatch.domain.model.people import Practitioner, RosterState
from overwatch.domain.model.service import AvailableTime, ServiceProfile
from tests.integration.application.conftest import Seed
from tests.support.actors import ACTOR_TENANT
from tests.support.sealing import TEST_SEALER, text_of

pytestmark = pytest.mark.asyncio(loop_scope="session")

NOW = datetime(2026, 11, 6, 10, 0, tzinfo=UTC)
HASHER = HmacPhoneHasher(
    FixedSecretStore({PHONE_HASH_SECRET: b"phone-hash-test-secret-0123456789ab"})
)
ANA = "07700 900111"
BEN = "07700 900222"
STRANGER = "07700 900333"
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
    def __init__(self, factory: UnitOfWorkFactory, driver: AsyncDriver) -> None:
        self.factory = factory
        self.clock = FixedClock(NOW)
        ids = SequentialIds("rt")
        store = DriverIdempotencyStore(driver)
        self.add = AddRosterManager(factory, self.clock, ids, HASHER)
        self.list = ListRoster(factory, self.clock)
        self.handler = HandleInboundText(
            factory,
            self.clock,
            SequentialIds("hi"),
            store,
            InMemoryCache(self.clock),
            ReportCapacity(factory, self.clock, ids, store, sealer=TEST_SEALER),
            ConfirmCapacity(factory, self.clock, ids, store, sealer=TEST_SEALER),
            sealer=TEST_SEALER,
            check_in=CheckIn(factory, self.clock, ids),
            sign_off=SignOff(factory, self.clock),
        )
        self._count = 0

    async def person(self, name: str, mobile: str, service: str = "ucr-west") -> None:
        await self.add.execute(AddRosterManagerCommand(LEAD, service, name, mobile))

    async def say(self, mobile: str, text: str):
        self._count += 1
        return await self.handler.execute(
            HandleInboundTextCommand(
                idempotency_key=f"SM{self._count}",
                from_phone_hash=_hash(mobile),
                text=text,
                received_at=self.clock.now(),
            )
        )

    async def states(self, service: str = "ucr-west") -> dict[str, RosterState]:
        return {entry.name: entry.state for entry in await self.list.execute(LEAD, service)}

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
    return Rig(uow_factory, neo4j_driver)


async def test_on_puts_the_person_on_shift_for_eight_hours_and_tells_them_so(rig: Rig) -> None:
    await rig.person("Ana Duty", ANA)

    result = await rig.say(ANA, "ON")

    assert result.outcome == ROSTER_ON
    assert await rig.states() == {"Ana Duty": RosterState.ON_SHIFT}
    assert await rig.sent() == [
        "Overwatch: you are on shift for UCR West until 18:00. Reply OFF when you finish."
    ]


async def test_on_with_hours_sets_the_length_and_it_reads_in_any_case_and_spacing(rig: Rig) -> None:
    await rig.person("Ana Duty", ANA)

    await rig.say(ANA, "  on  4h ")

    assert (await rig.sent())[0].endswith("until 14:00. Reply OFF when you finish.")


async def test_on_is_for_every_service_the_person_is_on_the_roster_of(rig: Rig) -> None:
    await rig.person("Ana Duty", ANA)
    await rig.person("Ana Duty", ANA, service="ucr-east")

    await rig.say(ANA, "ON 6")

    assert await rig.states("ucr-east") == {"Ana Duty": RosterState.ON_SHIFT}
    assert (await rig.sent())[0].startswith("Overwatch: you are on shift for UCR West and UCR East")


async def test_the_newest_on_replaces_the_last_person_on_shift(rig: Rig) -> None:
    await rig.person("Ana Duty", ANA)
    await rig.person("Ben Duty", BEN)
    await rig.say(ANA, "ON")

    await rig.say(BEN, "ON")

    assert await rig.states() == {
        "Ana Duty": RosterState.OFF_SHIFT,
        "Ben Duty": RosterState.ON_SHIFT,
    }


async def test_off_puts_the_person_off_shift_and_tells_them_so(rig: Rig) -> None:
    await rig.person("Ana Duty", ANA)
    await rig.say(ANA, "ON")

    result = await rig.say(ANA, "OFF")

    assert result.outcome == ROSTER_OFF
    assert await rig.states() == {"Ana Duty": RosterState.OFF_SHIFT}
    assert (await rig.sent())[-1] == "Overwatch: you are off shift for UCR West. Thank you."


async def test_off_when_not_on_shift_says_so_and_changes_nothing(rig: Rig) -> None:
    await rig.person("Ana Duty", ANA)

    result = await rig.say(ANA, "OFF")

    assert result.outcome == ROSTER_NOT_ON
    assert await rig.sent() == ["Overwatch: you are not on shift."]


async def test_a_shift_longer_than_the_longest_is_not_read_as_a_check_in(rig: Rig) -> None:
    await rig.person("Ana Duty", ANA)

    await rig.say(ANA, "ON 20")

    assert await rig.states() == {"Ana Duty": RosterState.OFF_SHIFT}


async def test_a_phone_on_no_roster_is_not_read_here(rig: Rig) -> None:
    await rig.person("Ana Duty", ANA)

    result = await rig.say(STRANGER, "ON")

    assert result.outcome == "dropped"
    assert await rig.sent() == []


async def test_the_same_text_delivered_twice_tells_the_person_once(rig: Rig) -> None:
    await rig.person("Ana Duty", ANA)
    command = HandleInboundTextCommand(
        idempotency_key="SM-same", from_phone_hash=_hash(ANA), text="ON", received_at=NOW
    )

    await rig.handler.execute(command)
    replay = await rig.handler.execute(command)

    assert replay.outcome == ROSTER_ON
    assert len(await rig.sent()) == 1


async def test_the_reply_is_sealed_and_the_text_holds_no_number(rig: Rig) -> None:
    await rig.person("Ana Duty", ANA)
    await rig.say(ANA, "ON")
    async with rig.factory() as uow:
        message = next(m for m in await uow.outbox.pending(100) if m.event_type == "SendMessage")

    assert "sealed_content" in message.payload
    assert "text" not in message.payload
    assert "07700" not in json.dumps(message.payload, default=str)
    assert set(message.payload) == {
        "communication_id",
        "message_id",
        "channel",
        "recipient_role_id",
        "sealed_content",
    }
    assert message.payload["message_id"] == "S1"
