"""Integration tests for HandleInboundText (U05), on the real Neo4j and an InMemoryCache.

Friday 23 October 2026, London time (BST, UTC+1). UCR West has a figure of 3 from 08:15. A C1 prompt
went to its reporter at 10:00 (sent with U03, `SendPrompts`), so its reply-by is 10:30. Every
assertion reads back through a fresh unit of work or a raw read. The phone hash is a synthetic
64-character hex string (the person repository refuses anything else), where the prompt's sample
says "ph-123". No patient data: the texts are numbers and the words "hello" and "yes".
"""

import dataclasses
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, time, timedelta
from typing import Any

import pytest
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.content_seal.aes_gcm import AesGcmContentSealer
from diucs.adapters.outbound.graph_store.idempotency_store import DriverIdempotencyStore
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.application.actor import Actor
from diucs.application.ports.outbound.audit import canonical_entry_json
from diucs.application.ports.outbound.messaging import Communication
from diucs.application.ports.outbound.tokens import LinkTokenRepository, LinkTokenService
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.confirm_capacity import (
    ConfirmCapacity,
    ConfirmCapacityCommand,
    ConfirmCapacityResult,
)
from diucs.application.use_cases.handle_inbound_text import (
    BOOKING_NOT_HANDLED,
    CONFIRM_LIMIT,
    CONFIRMED,
    DROPPED,
    HELP,
    LATE,
    NEED_NUMBER,
    RECHECK,
    RECORDED,
    STALE_FIGURE,
    HandleInboundText,
    HandleInboundTextCommand,
    HandleInboundTextResult,
)
from diucs.application.use_cases.report_capacity import (
    ReportCapacity,
    ReportCapacityCommand,
    ReportCapacityResult,
)
from diucs.application.use_cases.send_prompts import SendPromptCommand, SendPrompts
from diucs.domain.codes import (
    Cadence,
    Channel,
    Measure,
    PractitionerRoleCode,
    ReportFlagReason,
    ReportSource,
    ReportType,
    Role,
    ServiceCategory,
)
from diucs.domain.errors import ConfirmLimitReached, Conflict, NothingToConfirm, ValidationFailed
from diucs.domain.messages.catalogue import MessageId
from diucs.domain.messages.templates import render
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.people import Practitioner, PractitionerRole
from diucs.domain.model.service import AvailableTime, ServiceProfile
from tests.support.neo4j import count_nodes, read_tx

Seed = Callable[..., Awaitable[None]]

pytestmark = pytest.mark.asyncio(loop_scope="session")

PHONE = "ab" * 32
OTHER_PHONE = "cd" * 32
UNKNOWN_PHONE = "ee" * 32
LINK_SECRET = b"link-token-test-secret-0123456789abcdef"
ANYTIME = datetime(2000, 1, 1, tzinfo=UTC)
LONG_AGO = datetime(2026, 10, 22, 7, 15, tzinfo=UTC)  # 08:15 BST the day before

SYSTEM_ACTOR = Actor(
    role=Role.OWNER, practitioner_id=None, device_id=None, channel="worker", service_ids=frozenset()
)


def bst(hour: int, minute: int, second: int = 0, day: int = 23) -> datetime:
    """A London (BST) wall time in October 2026 as a UTC instant."""
    return datetime(2026, 10, day, hour, minute, second, tzinfo=UTC) - timedelta(hours=1)


def _profile(service_id: str, name: str, **changes: Any) -> ServiceProfile:
    profile = ServiceProfile(
        id=service_id,
        name=name,
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
    return dataclasses.replace(profile, **changes)


UCR_WEST = _profile("ucr-west", "UCR West")
UCR_EAST = _profile("ucr-east", "UCR East")

ROLE_WEST = PractitionerRole(
    id="role-west",
    practitioner_id="prac-1",
    service_id="ucr-west",
    code=PractitionerRoleCode.DUTY_MANAGER,
    active=True,
    channel=Channel.TEXT,
    period_start=datetime(2026, 1, 1, tzinfo=UTC),
)
ROLE_EAST = dataclasses.replace(ROLE_WEST, id="role-east", service_id="ucr-east")


# --- seeding -------------------------------------------------------------------------------------


async def _seed_people(
    factory: UnitOfWorkFactory,
    roles: tuple[PractitionerRole, ...] = (ROLE_WEST,),
    phone: str | None = PHONE,
) -> None:
    async with factory() as uow:
        await uow.people.save_practitioner(
            Practitioner(id="prac-1", active=True, display_name="Reporter One", phone_hash=phone)
        )
        for role in roles:
            await uow.people.save_role(role)
        await uow.commit()


async def _seed_figure(
    factory: UnitOfWorkFactory,
    value: int = 3,
    at: datetime | None = None,
    service_id: str = "ucr-west",
    report_id: str | None = None,
    report_type: ReportType = ReportType.NUMBER,
) -> None:
    at = at or bst(8, 15)
    async with factory() as uow:
        await uow.capacity.add(
            CapacityReport(
                id=report_id or f"seed-{service_id}",
                service_id=service_id,
                value=value,
                measure=Measure.REFERRALS_ACCEPTABLE,
                effective_at=at,
                source=ReportSource.TEXT,
                report_type=report_type,
                derived_from=None if report_type is ReportType.NUMBER else "seed-original",
            )
        )
        await uow.commit()


async def _seed_prompt(
    factory: UnitOfWorkFactory,
    sent_at: datetime,
    *,
    message_id: str = "C1",
    role_id: str = "role-west",
    service_id: str = "ucr-west",
    prompt_id: str = "prompt-seeded",
    text: str = "DIUCS: UCR West. We have 3 referrals in the next 2 hrs (as of 23 Oct 08:15).",
) -> None:
    """A stored prompt, for tests that need a send time or a message that U03 would not make."""
    async with factory() as uow:
        await uow.communications.add(
            Communication(
                id=prompt_id,
                message_id=message_id,
                channel=Channel.TEXT,
                recipient_role_id=role_id,
                about_id=service_id,
                payload_text=text,
                sent_at=sent_at,
                delivery_status="sent",
            )
        )
        await uow.commit()


async def _send_c1(
    factory: UnitOfWorkFactory, driver: AsyncDriver, sent_at: datetime, due_key: str = "c1"
) -> None:
    """Send the capacity prompt through U03, as the product does."""
    clock = FixedClock(sent_at)

    def tokens(repo: LinkTokenRepository) -> LinkTokenService:
        return LinkTokenService(repo, FixedSecretStore({"link-token": LINK_SECRET}), clock)

    sender = SendPrompts(
        factory,
        clock,
        SequentialIds("prompt"),
        DriverIdempotencyStore(driver),
        tokens,
        "diucs.example",
        AesGcmContentSealer(FixedSecretStore({"link-token": LINK_SECRET})),
        "tenant-a",
    )
    result = await sender.execute(
        SendPromptCommand(
            idempotency_key=f"prompt:{due_key}:{sent_at.isoformat()}",
            actor=SYSTEM_ACTOR,
            service_id="ucr-west",
            due_at=sent_at,
        )
    )
    assert result.sent is True


def _c9_text() -> str:
    return render(
        MessageId.C9,
        Channel.TEXT,
        reply_by="10:30",
        items=[("A", "UCR East", 1), ("B", "UCR West", 3)],
    ).text


async def _seed_group(factory: UnitOfWorkFactory, sent_at: datetime | None = None) -> None:
    """Two services on one phone, prompted together by one C9 (U04 stores one communication per
    grouped service, all C9, with the same text): A) UCR East 1, B) UCR West 3."""
    sent_at = sent_at or bst(10, 0)
    await _seed_people(factory, (ROLE_WEST, ROLE_EAST))
    await _seed_figure(factory, 3, bst(8, 15), "ucr-west")
    await _seed_figure(factory, 1, bst(8, 20), "ucr-east")
    for service_id, role_id in (("ucr-east", "role-east"), ("ucr-west", "role-west")):
        await _seed_prompt(
            factory,
            sent_at,
            message_id="C9",
            role_id=role_id,
            service_id=service_id,
            prompt_id=f"c9-{service_id}",
            text=_c9_text(),
        )


# --- the rig -------------------------------------------------------------------------------------


class SpyReports:
    """The real ReportCapacity, with a record of the commands it was given."""

    def __init__(self, inner: ReportCapacity) -> None:
        self._inner = inner
        self.commands: list[ReportCapacityCommand] = []

    async def execute(self, command: ReportCapacityCommand) -> ReportCapacityResult:
        self.commands.append(command)
        return await self._inner.execute(command)


class SpyConfirms:
    """The real ConfirmCapacity, with a record of the commands, and an error to raise on demand."""

    def __init__(self, inner: ConfirmCapacity) -> None:
        self._inner = inner
        self.commands: list[ConfirmCapacityCommand] = []
        self.raises: Exception | None = None

    async def execute(self, command: ConfirmCapacityCommand) -> ConfirmCapacityResult:
        self.commands.append(command)
        if self.raises is not None:
            raise self.raises
        return await self._inner.execute(command)


class Rig:
    def __init__(
        self,
        factory: UnitOfWorkFactory,
        driver: AsyncDriver,
        now: datetime | None = None,
        use_case_factory: UnitOfWorkFactory | None = None,
    ) -> None:
        self.factory = factory
        self.clock = FixedClock(now or bst(10, 12))
        self.cache = InMemoryCache(self.clock)
        ids = SequentialIds("in")
        store = DriverIdempotencyStore(driver)
        self.reports = SpyReports(ReportCapacity(factory, self.clock, ids, store))
        self.confirms = SpyConfirms(ConfirmCapacity(factory, self.clock, ids, store))
        self.use_case = HandleInboundText(
            use_case_factory or factory,
            self.clock,
            ids,
            store,
            self.cache,
            self.reports,  # type: ignore[arg-type]
            self.confirms,  # type: ignore[arg-type]
        )
        self._count = 0

    async def say(
        self,
        text: str,
        at: datetime | None = None,
        *,
        key: str | None = None,
        phone: str = PHONE,
        received_at: datetime | None = None,
    ) -> HandleInboundTextResult:
        if at is not None:
            self.clock.set(at)
        self._count += 1
        return await self.use_case.execute(
            HandleInboundTextCommand(
                idempotency_key=key or f"SM{self._count}",
                from_phone_hash=phone,
                text=text,
                received_at=received_at or self.clock.now(),
            )
        )


# --- reading back --------------------------------------------------------------------------------


async def _reports(
    factory: UnitOfWorkFactory, service_id: str = "ucr-west"
) -> list[CapacityReport]:
    async with factory() as uow:
        found = await uow.capacity.reports_since(service_id, ANYTIME)
    return sorted(found, key=lambda report: (report.effective_at, report.id))


async def _latest(factory: UnitOfWorkFactory, service_id: str = "ucr-west") -> CapacityReport:
    async with factory() as uow:
        latest = await uow.capacity.latest(service_id)
    assert latest is not None
    return latest


async def _communications(driver: AsyncDriver) -> list[dict[str, Any]]:
    async def work(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        result = await tx.run(
            "MATCH (c:Communication)-[:TOPIC]->(t:Concept) "
            "OPTIONAL MATCH (c)-[:RECIPIENT]->(r:PractitionerRole) "
            "OPTIONAL MATCH (c)-[:ABOUT]->(s:HealthcareService) "
            "OPTIONAL MATCH (c)-[:IN_RESPONSE_TO]->(p:Communication) "
            "RETURN c.id AS id, c.payloadText AS text, c.deliveryStatus AS status, "
            "t.code AS messageId, r.id AS role, s.id AS about, p.id AS inResponseTo "
            "ORDER BY c.id"
        )
        return await result.data()

    return await read_tx(driver, work)


async def _replies(driver: AsyncDriver, *skip: str) -> list[dict[str, Any]]:
    """Communications made after the prompts: every one except those with an id in `skip`, and
    except the prompts themselves (C1, C2 and C9 sent before the reply)."""
    rows = await _communications(driver)
    return [r for r in rows if r["id"] not in skip and not r["id"].startswith(("prompt", "c9-"))]


async def _total_nodes(driver: AsyncDriver) -> int:
    async def work(tx: AsyncManagedTransaction) -> int:
        record = await (await tx.run("MATCH (n) RETURN count(n) AS total")).single()
        assert record is not None
        return int(record["total"])

    return await read_tx(driver, work)


async def _send_messages(factory: UnitOfWorkFactory) -> list[Any]:
    async with factory() as uow:
        pending = await uow.outbox.pending(limit=1000)
    return [m for m in pending if m.event_type == "SendMessage"]


async def _handle_audits(factory: UnitOfWorkFactory) -> list[Any]:
    async with factory() as uow:
        records = await uow.audit.records()
    return [r for r in records if r.entry.use_case == "HandleInboundText"]


async def _one_reporter_one_prompt(
    factory: UnitOfWorkFactory,
    driver: AsyncDriver,
    seed_service: Seed,
    *,
    prompt_at: datetime | None = None,
    figure_at: datetime | None = None,
) -> None:
    await seed_service(UCR_WEST)
    await _seed_people(factory)
    await _seed_figure(factory, 3, figure_at or bst(8, 15))
    await _send_c1(factory, driver, prompt_at or bst(10, 0))


# --- the ten tests of the prompt -----------------------------------------------------------------


async def test_a_number_is_recorded_and_echoed_as_c3(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _one_reporter_one_prompt(uow_factory, neo4j_driver, seed_service)
    rig = Rig(uow_factory, neo4j_driver)

    result = await rig.say("4", bst(10, 12))

    assert result == HandleInboundTextResult(RECORDED, ("ucr-west",))
    latest = await _latest(uow_factory)
    assert (latest.value, latest.report_type, latest.source) == (
        4,
        ReportType.NUMBER,
        ReportSource.TEXT,
    )
    assert latest.effective_at == bst(10, 12)
    assert latest.performer_role_id == "role-west"
    [echo] = await _replies(neo4j_driver)
    assert echo["messageId"] == "C3"
    assert echo["role"] == "role-west"
    assert echo["about"] == "ucr-west"
    assert echo["status"] == "queued"
    assert echo["text"].startswith("Thanks. UCR West: 4 referrals in the next 2 hrs, as of 10:12.")
    [sent] = await _send_messages(uow_factory)
    assert sent.payload["recipient_role_id"] == "role-west"


async def test_a_y_with_spaces_and_lower_case_confirms_the_figure(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _one_reporter_one_prompt(uow_factory, neo4j_driver, seed_service)
    rig = Rig(uow_factory, neo4j_driver)

    result = await rig.say(" y ", bst(10, 5))

    assert result == HandleInboundTextResult(CONFIRMED, ("ucr-west",))
    reports = await _reports(uow_factory)
    assert [(r.value, r.report_type) for r in reports] == [
        (3, ReportType.NUMBER),
        (3, ReportType.CONFIRMED),
    ]
    assert reports[1].effective_at == bst(10, 5)
    assert reports[1].derived_from == reports[0].id
    assert reports[1].performer_role_id == "role-west"
    [echo] = await _replies(neo4j_driver)
    assert echo["messageId"] == "C3"


async def test_a_number_after_the_reply_by_is_refused_with_c5(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _one_reporter_one_prompt(uow_factory, neo4j_driver, seed_service, prompt_at=bst(12, 0))
    rig = Rig(uow_factory, neo4j_driver)

    result = await rig.say("5", bst(12, 41))

    assert result == HandleInboundTextResult(LATE, ("ucr-west",))
    assert len(await _reports(uow_factory)) == 1
    [refusal] = await _replies(neo4j_driver)
    assert refusal["messageId"] == "C5"
    assert refusal["text"] == (
        "Too late: the 12:30 cut-off had passed, so 5 was not used. "
        "New question: UCR West has 3 referrals in the next 2 hrs recorded. "
        "Reply Y if right, or send the new number, by 13:11."
    )
    assert refusal["role"] == "role-west"


async def test_a_third_y_in_a_row_is_refused_with_c6(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _one_reporter_one_prompt(uow_factory, neo4j_driver, seed_service)
    rig = Rig(uow_factory, neo4j_driver)
    assert (await rig.say("Y", bst(10, 5))).outcome == CONFIRMED
    assert (await rig.say("Y", bst(10, 6))).outcome == CONFIRMED
    reports_before = len(await _reports(uow_factory))

    result = await rig.say("Y", bst(10, 7))

    assert result == HandleInboundTextResult(CONFIRM_LIMIT, ("ucr-west",))
    assert len(await _reports(uow_factory)) == reports_before == 3
    rows = await _replies(neo4j_driver)
    assert [r["messageId"] for r in rows] == ["C3", "C3", "C6"]
    assert rows[2]["text"] == "Y was used twice already. Please send the number for UCR West."


async def test_an_out_of_range_figure_asks_again_and_the_same_figure_twice_is_recorded_flagged(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _one_reporter_one_prompt(uow_factory, neo4j_driver, seed_service)
    rig = Rig(uow_factory, neo4j_driver)

    first = await rig.say("40", bst(10, 12))

    assert first == HandleInboundTextResult(RECHECK, ("ucr-west",))
    assert len(await _reports(uow_factory)) == 1
    assert await rig.cache.get(f"recheck:{PHONE}:ucr-west") == "40"
    [ask] = await _replies(neo4j_driver)
    assert ask["messageId"] == "C7"
    assert ask["text"] == (
        "UCR West: 40 is outside the usual range of 0 to 8. If it is right, send 40 again."
    )

    second = await rig.say("40", bst(10, 13))

    assert second == HandleInboundTextResult(RECORDED, ("ucr-west",))
    assert (await _latest(uow_factory)).value == 40
    # The flag is passed to ReportCapacity (DEC-148 item 7 says what happens until U07 records it).
    assert rig.reports.commands[0].flag is ReportFlagReason.OUT_OF_RANGE_TWICE
    assert await rig.cache.get(f"recheck:{PHONE}:ucr-west") is None


async def test_a_repeat_of_a_different_figure_is_asked_again_not_recorded(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _one_reporter_one_prompt(uow_factory, neo4j_driver, seed_service)
    rig = Rig(uow_factory, neo4j_driver)
    await rig.say("40", bst(10, 12))

    result = await rig.say("50", bst(10, 13))

    assert result.outcome == RECHECK
    assert len(await _reports(uow_factory)) == 1
    assert await rig.cache.get(f"recheck:{PHONE}:ucr-west") == "50"


async def test_a_number_that_corrects_one_just_accepted_is_echoed_as_c4(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _one_reporter_one_prompt(uow_factory, neo4j_driver, seed_service, prompt_at=bst(14, 0))
    rig = Rig(uow_factory, neo4j_driver)
    assert (await rig.say("4", bst(14, 10))).outcome == RECORDED

    result = await rig.say("3", bst(14, 14))

    assert result == HandleInboundTextResult(RECORDED, ("ucr-west",))
    assert (await _latest(uow_factory)).value == 3
    rows = await _replies(neo4j_driver)
    assert [r["messageId"] for r in rows] == ["C3", "C4"]
    assert rows[1]["text"] == (
        "Updated: UCR West 3 referrals in the next 2 hrs, as of 14:14. Replaces 4."
    )
    assert rig.reports.commands[1].replaced_value == 4


async def test_words_that_mean_nothing_get_the_help_text(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _one_reporter_one_prompt(uow_factory, neo4j_driver, seed_service)
    rig = Rig(uow_factory, neo4j_driver)

    result = await rig.say("hello", bst(10, 5))

    assert result == HandleInboundTextResult(HELP, ("ucr-west",))
    assert len(await _reports(uow_factory)) == 1
    [help_text] = await _replies(neo4j_driver)
    assert help_text["messageId"] == "C11"
    assert help_text["role"] == "role-west"
    assert help_text["text"] == render(MessageId.C11, Channel.TEXT).text


async def test_a_text_from_an_unknown_phone_is_dropped_and_writes_nothing(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _one_reporter_one_prompt(uow_factory, neo4j_driver, seed_service)
    rig = Rig(uow_factory, neo4j_driver)
    nodes_before = await _total_nodes(neo4j_driver)

    result = await rig.say("4", bst(10, 12), phone=UNKNOWN_PHONE)

    assert result == HandleInboundTextResult(DROPPED, ())
    assert await _total_nodes(neo4j_driver) == nodes_before
    assert await _send_messages(uow_factory) == [
        m for m in await _send_messages(uow_factory) if m.payload["message_id"] == "C1"
    ]


async def test_one_service_answered_on_a_grouped_prompt_leaves_the_other_waiting(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST, UCR_EAST)
    await _seed_group(uow_factory)
    rig = Rig(uow_factory, neo4j_driver)

    result = await rig.say("B 2", bst(10, 12))

    assert result == HandleInboundTextResult(RECORDED, ("ucr-west",))
    assert (await _latest(uow_factory, "ucr-west")).value == 2
    assert [r.value for r in await _reports(uow_factory, "ucr-east")] == [1]
    [thanks] = await _replies(neo4j_driver)
    assert thanks["messageId"] == "C10"
    assert thanks["text"] == (
        "Thanks. B) UCR West updated to 2. A) UCR East still needs a reply: Y A, or A and a number."
    )
    # No per-service C3 for a grouped reply: one C10 says it all.
    assert [m.payload["message_id"] for m in await _send_messages(uow_factory)] == ["C10"]


async def test_y_with_a_letter_confirms_that_service_only(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST, UCR_EAST)
    await _seed_group(uow_factory)
    rig = Rig(uow_factory, neo4j_driver)
    await rig.say("B 2", bst(10, 12))

    result = await rig.say("Y A", bst(10, 13))

    assert result == HandleInboundTextResult(CONFIRMED, ("ucr-east",))
    east = await _reports(uow_factory, "ucr-east")
    assert [(r.value, r.report_type) for r in east] == [
        (1, ReportType.NUMBER),
        (1, ReportType.CONFIRMED),
    ]
    assert [r.value for r in await _reports(uow_factory, "ucr-west")] == [3, 2]
    rows = await _replies(neo4j_driver)
    assert rows[-1]["messageId"] == "C10"
    assert rows[-1]["text"] == "Thanks. A) UCR East updated to 1."


async def test_a_plain_y_on_a_grouped_prompt_confirms_every_service(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST, UCR_EAST)
    await _seed_group(uow_factory)
    rig = Rig(uow_factory, neo4j_driver)

    result = await rig.say("Y", bst(10, 5))

    assert result == HandleInboundTextResult(CONFIRMED, ("ucr-east", "ucr-west"))
    for service_id, value in (("ucr-east", 1), ("ucr-west", 3)):
        latest = await _latest(uow_factory, service_id)
        assert (latest.value, latest.report_type) == (value, ReportType.CONFIRMED)
    [thanks] = await _replies(neo4j_driver)
    assert thanks["text"] == "Thanks. A) UCR East updated to 1. B) UCR West updated to 3."
    assert [c.send_echo for c in rig.confirms.commands] == [False, False]


async def test_the_same_provider_message_id_twice_writes_nothing_new(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _one_reporter_one_prompt(uow_factory, neo4j_driver, seed_service)
    rig = Rig(uow_factory, neo4j_driver)
    first = await rig.say("4", bst(10, 12), key="SM-provider-1")
    nodes_after_first = await _total_nodes(neo4j_driver)

    again = await rig.say("4", bst(10, 12), key="SM-provider-1")

    assert again == dataclasses.replace(first, replayed=True)
    assert await _total_nodes(neo4j_driver) == nodes_after_first
    assert len(await _reports(uow_factory)) == 2


async def test_a_y_on_a_figure_from_the_day_before_is_not_recorded_as_current(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    """Hazard H-31. The C1 at 12:00 shows 3 as of 22 Oct 08:15. A Y at 12:05 must not make it
    current: the reporter is told it is out of date and asked for a number."""
    await _one_reporter_one_prompt(
        uow_factory, neo4j_driver, seed_service, prompt_at=bst(12, 0), figure_at=LONG_AGO
    )
    rig = Rig(uow_factory, neo4j_driver)

    result = await rig.say("Y", bst(12, 5))

    assert result == HandleInboundTextResult(STALE_FIGURE, ("ucr-west",))
    reports = await _reports(uow_factory)
    assert [(r.value, r.report_type, r.effective_at) for r in reports] == [
        (3, ReportType.NUMBER, LONG_AGO)
    ]
    assert rig.confirms.commands == []
    [refusal] = await _replies(neo4j_driver)
    assert refusal["messageId"] == "C12"
    assert refusal["text"] == (
        "DIUCS: UCR West. The figure on record, 3 referrals in the next 2 hrs, is out of date "
        "(as of 22 Oct 08:15), so Y was not used. Send a number (0 = closed). By 12:35."
    )
    assert refusal["role"] == "role-west"


async def test_the_number_asked_for_after_a_stale_y_is_recorded(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _one_reporter_one_prompt(
        uow_factory, neo4j_driver, seed_service, prompt_at=bst(12, 0), figure_at=LONG_AGO
    )
    rig = Rig(uow_factory, neo4j_driver)
    await rig.say("Y", bst(12, 5))

    result = await rig.say("4", bst(12, 8))

    assert result == HandleInboundTextResult(RECORDED, ("ucr-west",))
    assert (await _latest(uow_factory)).value == 4


async def test_a_second_y_after_the_refusal_is_refused_again_not_confirmed(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _one_reporter_one_prompt(
        uow_factory, neo4j_driver, seed_service, prompt_at=bst(12, 0), figure_at=LONG_AGO
    )
    rig = Rig(uow_factory, neo4j_driver)
    await rig.say("Y", bst(12, 5))

    # The C12 is the open question now (sent 12:05, reply-by 12:35): a Y to it is judged against
    # the same figure, which is still out of date.
    result = await rig.say("Y", bst(12, 20))

    assert result.outcome == STALE_FIGURE
    assert len(await _reports(uow_factory)) == 1
    assert [r["messageId"] for r in await _replies(neo4j_driver)] == ["C12", "C12"]


# --- hazard H-31 at the window boundary, with the London clock-change days (lesson L4) -----------

SPRING_SENT = datetime(2026, 3, 29, 2, 30, tzinfo=UTC)  # 03:30 BST, 90 minutes after the change
AUTUMN_SENT = datetime(2026, 10, 25, 2, 30, tzinfo=UTC)  # 02:30 GMT, 90 minutes after the change
ORDINARY_SENT = datetime(2026, 10, 23, 11, 0, tzinfo=UTC)  # 12:00 BST


@pytest.mark.parametrize(
    ("sent_at", "age", "expected"),
    [
        (sent, age, expected)
        for sent in (ORDINARY_SENT, SPRING_SENT, AUTUMN_SENT)
        for age, expected in (
            (timedelta(hours=2) - timedelta(seconds=1), CONFIRMED),  # inside the window
            (timedelta(hours=2), CONFIRMED),  # at the window
            (timedelta(hours=2) + timedelta(seconds=1), STALE_FIGURE),  # after the window
        )
    ],
    ids=lambda value: str(value) if isinstance(value, timedelta | datetime) else value,
)
async def test_a_y_is_recorded_only_while_the_figure_is_inside_its_window(
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    seed_service: Seed,
    sent_at: datetime,
    age: timedelta,
    expected: str,
) -> None:
    await seed_service(UCR_WEST)
    await _seed_people(uow_factory)
    await _seed_figure(uow_factory, 3, sent_at - age)
    await _seed_prompt(uow_factory, sent_at)
    rig = Rig(uow_factory, neo4j_driver, now=sent_at)

    result = await rig.say("Y", sent_at + timedelta(minutes=5))

    assert result.outcome == expected
    reports = await _reports(uow_factory)
    if expected == CONFIRMED:
        assert [r.report_type for r in reports] == [ReportType.NUMBER, ReportType.CONFIRMED]
        assert reports[1].effective_at == sent_at + timedelta(minutes=5)
    else:
        assert [(r.report_type, r.effective_at) for r in reports] == [
            (ReportType.NUMBER, sent_at - age)
        ]


async def test_a_figure_reported_after_the_prompt_is_not_judged_out_of_date(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    """A figure reported after the prompt was sent (by link, say) is not out of date: its age at
    the prompt's send time is negative."""
    await seed_service(UCR_WEST)
    await _seed_people(uow_factory)
    await _seed_figure(uow_factory, 3, LONG_AGO)
    await _seed_prompt(uow_factory, bst(12, 0))
    await _seed_figure(uow_factory, 5, bst(12, 3), report_id="seed-link")
    rig = Rig(uow_factory, neo4j_driver)

    result = await rig.say("Y", bst(12, 5))

    assert result.outcome == CONFIRMED
    assert (await _latest(uow_factory)).value == 5


# --- the other refusals and the help paths -------------------------------------------------------


async def test_a_late_y_is_refused_with_c5_naming_the_y(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _one_reporter_one_prompt(uow_factory, neo4j_driver, seed_service, prompt_at=bst(12, 0))
    rig = Rig(uow_factory, neo4j_driver)

    result = await rig.say("Y", bst(12, 41))

    assert result.outcome == LATE
    [refusal] = await _replies(neo4j_driver)
    assert refusal["text"].startswith("Too late: the 12:30 cut-off had passed, so Y was not used.")
    assert len(await _reports(uow_factory)) == 1


async def test_a_late_number_for_a_service_with_no_figure_is_asked_for_with_c2(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)
    await _seed_people(uow_factory)
    await _seed_prompt(uow_factory, bst(8, 0), message_id="C2", text="first prompt")
    rig = Rig(uow_factory, neo4j_driver)

    result = await rig.say("5", bst(8, 41))

    assert result == HandleInboundTextResult(LATE, ("ucr-west",))
    [refusal] = await _replies(neo4j_driver, "prompt-seeded")
    assert refusal["messageId"] == "C2"
    assert refusal["text"] == (
        "DIUCS: UCR West. How many referrals can you take in the next 2 hrs? "
        "Send a number (0 = closed). By 09:11."
    )
    assert await _reports(uow_factory) == []


async def test_a_y_for_a_service_with_no_figure_asks_for_a_number(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)
    await _seed_people(uow_factory)
    await _seed_prompt(uow_factory, bst(8, 0), message_id="C2", text="first prompt")
    rig = Rig(uow_factory, neo4j_driver)

    result = await rig.say("Y", bst(8, 5))

    assert result == HandleInboundTextResult(NEED_NUMBER, ("ucr-west",))
    [ask] = await _replies(neo4j_driver, "prompt-seeded")
    assert ask["messageId"] == "C2"
    assert ask["text"].endswith("Send a number (0 = closed). By 08:35.")
    assert await _reports(uow_factory) == []


async def test_a_unit_label_with_no_window_cannot_word_c2_so_the_help_text_is_sent(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(dataclasses.replace(UCR_WEST, unit_label="referrals"))
    await _seed_people(uow_factory)
    await _seed_prompt(uow_factory, bst(8, 0), message_id="C2", text="first prompt")
    rig = Rig(uow_factory, neo4j_driver)

    result = await rig.say("Y", bst(8, 5))

    assert result == HandleInboundTextResult(NEED_NUMBER, ("ucr-west",))
    [ask] = await _replies(neo4j_driver, "prompt-seeded")
    assert ask["messageId"] == "C11"


async def test_a_booking_word_is_not_handled_here_and_nothing_is_written(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _one_reporter_one_prompt(uow_factory, neo4j_driver, seed_service)
    rig = Rig(uow_factory, neo4j_driver)
    nodes_before = await _total_nodes(neo4j_driver)

    result = await rig.say("CONFIRMED 4821", bst(10, 5))

    assert result == HandleInboundTextResult(BOOKING_NOT_HANDLED, ())
    assert await _total_nodes(neo4j_driver) == nodes_before


async def test_a_known_person_who_reports_for_no_service_is_dropped(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)
    await _seed_people(uow_factory, roles=())
    rig = Rig(uow_factory, neo4j_driver)
    nodes_before = await _total_nodes(neo4j_driver)

    result = await rig.say("4", bst(10, 5))

    assert result == HandleInboundTextResult(DROPPED, ())
    assert await _total_nodes(neo4j_driver) == nodes_before


async def test_a_reply_when_no_prompt_was_ever_sent_gets_the_help_text(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)
    await _seed_people(uow_factory)
    await _seed_figure(uow_factory)
    rig = Rig(uow_factory, neo4j_driver)

    result = await rig.say("4", bst(10, 5))

    assert result == HandleInboundTextResult(HELP, ("ucr-west",))
    [help_text] = await _replies(neo4j_driver)
    assert help_text["messageId"] == "C11"
    assert len(await _reports(uow_factory)) == 1


async def test_a_reply_for_a_service_that_is_no_longer_active_is_dropped(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(dataclasses.replace(UCR_WEST, active=False))
    await _seed_people(uow_factory)
    await _seed_figure(uow_factory)
    await _seed_prompt(uow_factory, bst(10, 0))
    rig = Rig(uow_factory, neo4j_driver)
    nodes_before = await _total_nodes(neo4j_driver)

    result = await rig.say("4", bst(10, 5))

    assert result == HandleInboundTextResult(DROPPED, ())
    assert await _total_nodes(neo4j_driver) == nodes_before


async def test_a_lettered_reply_to_a_prompt_for_one_service_is_not_understood(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _one_reporter_one_prompt(uow_factory, neo4j_driver, seed_service)
    rig = Rig(uow_factory, neo4j_driver)

    result = await rig.say("A 4", bst(10, 5))

    assert result.outcome == HELP
    assert len(await _reports(uow_factory)) == 1


# --- grouped prompts: nothing is guessed ---------------------------------------------------------


@pytest.mark.parametrize("text", ["4", "C 2", "Y C", "B 2, C 1", "A 1, B"])
async def test_a_grouped_reply_that_does_not_name_a_service_of_the_group_records_nothing(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed, text: str
) -> None:
    await seed_service(UCR_WEST, UCR_EAST)
    await _seed_group(uow_factory)
    rig = Rig(uow_factory, neo4j_driver)

    result = await rig.say(text, bst(10, 5))

    assert result.outcome == HELP
    assert [r.value for r in await _reports(uow_factory, "ucr-west")] == [3]
    assert [r.value for r in await _reports(uow_factory, "ucr-east")] == [1]
    [help_text] = await _replies(neo4j_driver)
    assert help_text["messageId"] == "C11"


@pytest.mark.parametrize("text", ["A 4", "Y", "Y A"])
async def test_letters_are_not_reapplied_when_a_service_has_left_the_phone_since_the_prompt(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed, text: str
) -> None:
    """The prompt said A) UCR East, B) UCR West. If East's role has gone, rebuilding the letters
    from what the phone holds now would make West "A". The reply must not be read that way."""
    await seed_service(UCR_WEST, UCR_EAST)
    await _seed_group(uow_factory)
    async with uow_factory() as uow:
        await uow.people.save_role(dataclasses.replace(ROLE_EAST, active=False))
        await uow.commit()
    rig = Rig(uow_factory, neo4j_driver)

    result = await rig.say(text, bst(10, 5))

    assert result.outcome == HELP
    assert [r.value for r in await _reports(uow_factory, "ucr-west")] == [3]
    assert [r.value for r in await _reports(uow_factory, "ucr-east")] == [1]


async def test_a_grouped_y_confirms_the_fresh_service_and_refuses_the_stale_one_with_its_letter(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST, UCR_EAST)
    await _seed_people(uow_factory, (ROLE_WEST, ROLE_EAST))
    await _seed_figure(uow_factory, 3, bst(8, 15), "ucr-west")
    await _seed_figure(uow_factory, 1, LONG_AGO, "ucr-east")
    for service_id, role_id in (("ucr-east", "role-east"), ("ucr-west", "role-west")):
        await _seed_prompt(
            uow_factory,
            bst(10, 0),
            message_id="C9",
            role_id=role_id,
            service_id=service_id,
            prompt_id=f"c9-{service_id}",
            text=_c9_text(),
        )
    rig = Rig(uow_factory, neo4j_driver)

    result = await rig.say("Y", bst(10, 5))

    assert result == HandleInboundTextResult(CONFIRMED, ("ucr-west",))
    assert [r.report_type for r in await _reports(uow_factory, "ucr-west")] == [
        ReportType.NUMBER,
        ReportType.CONFIRMED,
    ]
    assert [r.report_type for r in await _reports(uow_factory, "ucr-east")] == [ReportType.NUMBER]
    rows = {r["messageId"]: r for r in await _replies(neo4j_driver)}
    assert rows["C10"]["text"] == "Thanks. B) UCR West updated to 3."
    assert rows["C12"]["text"] == (
        "DIUCS: UCR East. The figure on record, 1 referrals in the next 2 hrs, is out of date "
        "(as of 22 Oct 08:15), so Y was not used. Send A and a number (0 = closed). By 10:35."
    )
    assert rows["C12"]["role"] == "role-east"


async def test_a_late_grouped_number_is_refused_for_that_service(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST, UCR_EAST)
    await _seed_group(uow_factory)
    rig = Rig(uow_factory, neo4j_driver)

    result = await rig.say("B 5", bst(10, 31))

    assert result == HandleInboundTextResult(LATE, ("ucr-west",))
    assert [r.value for r in await _reports(uow_factory, "ucr-west")] == [3]
    [refusal] = await _replies(neo4j_driver)
    assert refusal["messageId"] == "C5"
    assert refusal["text"].startswith("Too late: the 10:30 cut-off had passed, so 5 was not used.")
    assert refusal["role"] == "role-west"


async def test_two_lettered_figures_are_both_recorded_and_echoed_once(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST, UCR_EAST)
    await _seed_group(uow_factory)
    rig = Rig(uow_factory, neo4j_driver)

    result = await rig.say("A 2, B 4", bst(10, 12))

    assert result == HandleInboundTextResult(RECORDED, ("ucr-east", "ucr-west"))
    assert (await _latest(uow_factory, "ucr-east")).value == 2
    assert (await _latest(uow_factory, "ucr-west")).value == 4
    [thanks] = await _replies(neo4j_driver)
    assert thanks["text"] == "Thanks. A) UCR East updated to 2. B) UCR West updated to 4."


async def test_a_mixed_grouped_reply_reports_the_recorded_outcome_first(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST, UCR_EAST)
    await _seed_group(uow_factory)
    rig = Rig(uow_factory, neo4j_driver)

    result = await rig.say("Y A, B 2", bst(10, 12))

    assert result == HandleInboundTextResult(RECORDED, ("ucr-west",))
    assert (await _latest(uow_factory, "ucr-east")).report_type is ReportType.CONFIRMED
    assert (await _latest(uow_factory, "ucr-west")).value == 2


async def test_a_grouped_out_of_range_figure_asks_again_with_its_own_cache_key(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST, UCR_EAST)
    await _seed_group(uow_factory)
    rig = Rig(uow_factory, neo4j_driver)

    result = await rig.say("A 40", bst(10, 12))

    assert result == HandleInboundTextResult(RECHECK, ("ucr-east",))
    assert await rig.cache.get(f"recheck:{PHONE}:ucr-east") == "40"
    assert await rig.cache.get(f"recheck:{PHONE}:ucr-west") is None
    assert [r.value for r in await _reports(uow_factory, "ucr-east")] == [1]


async def test_a_grouped_third_y_for_one_service_is_refused_with_c6(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST, UCR_EAST)
    await _seed_group(uow_factory)
    rig = Rig(uow_factory, neo4j_driver)
    await rig.say("Y A", bst(10, 5))
    await rig.say("Y A", bst(10, 6))

    result = await rig.say("Y A", bst(10, 7))

    assert result == HandleInboundTextResult(CONFIRM_LIMIT, ("ucr-east",))
    assert len(await _reports(uow_factory, "ucr-east")) == 3


# --- the cache key of an out-of-range figure -----------------------------------------------------


async def test_the_recheck_key_lasts_until_the_reply_by_and_no_longer(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _one_reporter_one_prompt(uow_factory, neo4j_driver, seed_service)
    rig = Rig(uow_factory, neo4j_driver)
    await rig.say("40", bst(10, 12))
    key = f"recheck:{PHONE}:ucr-west"

    rig.clock.set(bst(10, 29, 59))
    assert await rig.cache.get(key) == "40"
    rig.clock.set(bst(10, 30))
    assert await rig.cache.get(key) is None


async def test_a_figure_recorded_in_between_clears_the_pending_out_of_range_figure(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _one_reporter_one_prompt(uow_factory, neo4j_driver, seed_service)
    rig = Rig(uow_factory, neo4j_driver)
    await rig.say("40", bst(10, 12))
    await rig.say("5", bst(10, 13))
    assert await rig.cache.get(f"recheck:{PHONE}:ucr-west") is None

    result = await rig.say("40", bst(10, 14))

    # A fresh 40 is a first 40 again (it asks again), and is not recorded flagged.
    assert result.outcome == RECHECK
    assert (await _latest(uow_factory)).value == 5


async def test_a_y_clears_the_pending_out_of_range_figure(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _one_reporter_one_prompt(uow_factory, neo4j_driver, seed_service)
    rig = Rig(uow_factory, neo4j_driver)
    await rig.say("40", bst(10, 12))

    result = await rig.say("Y", bst(10, 13))

    assert result.outcome == CONFIRMED
    assert await rig.cache.get(f"recheck:{PHONE}:ucr-west") is None


async def test_an_out_of_range_correction_after_the_prompt_closed_keeps_its_key_long_enough(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    """A figure inside the 15-minute correction window is judged even after the reply-by. Its
    recheck key must outlive that moment, or the repeat could never be recorded."""
    await _one_reporter_one_prompt(uow_factory, neo4j_driver, seed_service)
    rig = Rig(uow_factory, neo4j_driver)
    await rig.say("4", bst(10, 28))

    first = await rig.say("40", bst(10, 35))
    assert first.outcome == RECHECK

    second = await rig.say("40", bst(10, 40))
    assert second == HandleInboundTextResult(RECORDED, ("ucr-west",))
    assert (await _latest(uow_factory)).value == 40


# --- time of the reply ---------------------------------------------------------------------------


async def test_a_reply_processed_late_is_judged_at_the_time_it_was_received(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _one_reporter_one_prompt(uow_factory, neo4j_driver, seed_service)
    rig = Rig(uow_factory, neo4j_driver)

    result = await rig.say("4", bst(10, 45), received_at=bst(10, 12))

    assert result.outcome == RECORDED
    assert (await _latest(uow_factory)).effective_at == bst(10, 45)


async def test_a_received_time_after_the_clock_is_not_believed(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _one_reporter_one_prompt(uow_factory, neo4j_driver, seed_service, prompt_at=bst(12, 0))
    rig = Rig(uow_factory, neo4j_driver)

    # At 12:41 the prompt has closed. A received time of 12:10 would make it open; one of 13:00
    # (in the future) must not be used to move the decision either way.
    late = await rig.say("5", bst(12, 41), received_at=bst(13, 0))

    assert late.outcome == LATE


async def test_a_naive_received_time_is_refused_and_nothing_is_written(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _one_reporter_one_prompt(uow_factory, neo4j_driver, seed_service)
    rig = Rig(uow_factory, neo4j_driver)
    nodes_before = await _total_nodes(neo4j_driver)

    with pytest.raises(ValidationFailed) as refused:
        await rig.say("4", bst(10, 12), received_at=datetime(2026, 10, 23, 10, 12))

    assert refused.value.field == "received_at"
    assert await _total_nodes(neo4j_driver) == nodes_before


# --- idempotency and recovery --------------------------------------------------------------------


async def test_a_provider_message_id_reused_for_another_text_is_a_conflict(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _one_reporter_one_prompt(uow_factory, neo4j_driver, seed_service)
    rig = Rig(uow_factory, neo4j_driver)
    await rig.say("4", bst(10, 12), key="SM-1")
    nodes_before = await _total_nodes(neo4j_driver)

    with pytest.raises(Conflict):
        await rig.say("5", bst(10, 12), key="SM-1")

    assert await _total_nodes(neo4j_driver) == nodes_before


async def test_a_provider_message_id_reused_from_another_phone_is_a_conflict(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _one_reporter_one_prompt(uow_factory, neo4j_driver, seed_service)
    rig = Rig(uow_factory, neo4j_driver)
    await rig.say("4", bst(10, 12), key="SM-1")

    with pytest.raises(Conflict):
        await rig.say("4", bst(10, 12), key="SM-1", phone=OTHER_PHONE)


class _AuditThatFailsOnce:
    def __init__(self, inner: Any, switch: _Switch) -> None:
        self._inner = inner
        self._switch = switch

    async def append(self, entry: Any) -> Any:
        if self._switch.armed and entry.use_case == "HandleInboundText":
            self._switch.armed = False
            raise RuntimeError("the audit write failed")
        return await self._inner.append(entry)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class _Switch:
    armed = True


class _UnitOfWorkWithFlakyAudit:
    def __init__(self, inner: Any, switch: _Switch) -> None:
        self._inner = inner
        self._switch = switch

    @property
    def audit(self) -> _AuditThatFailsOnce:
        return _AuditThatFailsOnce(self._inner.audit, self._switch)

    async def __aenter__(self) -> _UnitOfWorkWithFlakyAudit:
        await self._inner.__aenter__()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self._inner.__aexit__(*exc)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


@pytest.mark.parametrize(("text", "outcome"), [("4", RECORDED), ("Y", CONFIRMED)])
async def test_a_retry_after_a_failure_part_way_does_not_record_the_figure_twice(
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    seed_service: Seed,
    text: str,
    outcome: str,
) -> None:
    """The report is committed by ReportCapacity or ConfirmCapacity before this use case writes its
    own audit entry. If that write fails, the provider redelivers the same message id: the figure
    must be there once, not twice, and the retry must finish the job."""
    await _one_reporter_one_prompt(uow_factory, neo4j_driver, seed_service)
    switch = _Switch()

    def flaky() -> Any:
        return _UnitOfWorkWithFlakyAudit(uow_factory(), switch)

    rig = Rig(uow_factory, neo4j_driver, use_case_factory=flaky)
    with pytest.raises(RuntimeError):
        await rig.say(text, bst(10, 12), key="SM-retry")
    assert len(await _reports(uow_factory)) == 2
    assert await _handle_audits(uow_factory) == []

    result = await rig.say(text, bst(10, 14), key="SM-retry")

    assert result == HandleInboundTextResult(outcome, ("ucr-west",))
    assert len(await _reports(uow_factory)) == 2
    assert len(await _handle_audits(uow_factory)) == 1
    assert [r["messageId"] for r in await _replies(neo4j_driver)] == ["C3"]


# --- the sub use cases are asked, not copied -----------------------------------------------------


async def test_a_confirm_refused_by_confirm_capacity_is_answered_with_c6(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    """The count is read twice: here and again under the service lock in ConfirmCapacity. If two
    texts race, the second is refused there, and the reporter still gets the C6."""
    await _one_reporter_one_prompt(uow_factory, neo4j_driver, seed_service)
    rig = Rig(uow_factory, neo4j_driver)
    rig.confirms.raises = ConfirmLimitReached("confirmed twice in a row")

    result = await rig.say("Y", bst(10, 5))

    assert result == HandleInboundTextResult(CONFIRM_LIMIT, ("ucr-west",))
    [refusal] = await _replies(neo4j_driver)
    assert refusal["messageId"] == "C6"


async def test_a_confirm_with_nothing_to_confirm_by_the_time_it_runs_asks_for_a_number(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _one_reporter_one_prompt(uow_factory, neo4j_driver, seed_service)
    rig = Rig(uow_factory, neo4j_driver)
    rig.confirms.raises = NothingToConfirm("this service has no report to confirm")

    result = await rig.say("Y", bst(10, 5))

    assert result == HandleInboundTextResult(NEED_NUMBER, ("ucr-west",))
    [ask] = await _replies(neo4j_driver)
    assert ask["messageId"] == "C2"


async def test_the_commands_name_the_reporter_the_text_source_and_the_role(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _one_reporter_one_prompt(uow_factory, neo4j_driver, seed_service)
    rig = Rig(uow_factory, neo4j_driver)
    await rig.say("4", bst(10, 12), key="SM-9")
    await rig.say("Y", bst(10, 13), key="SM-10")

    [report] = rig.reports.commands
    [confirm] = rig.confirms.commands
    for command in (report, confirm):
        assert command.actor == Actor(
            role=Role.REPORTER,
            practitioner_id="prac-1",
            device_id=None,
            channel="text",
            service_ids=frozenset({"ucr-west"}),
        )
        assert command.source is ReportSource.TEXT
        assert command.performer_role_id == "role-west"
        assert command.send_echo is True
        assert command.service_id == "ucr-west"
    assert report.idempotency_key != confirm.idempotency_key
    assert "SM-9" in report.idempotency_key
    assert "SM-10" in confirm.idempotency_key


async def test_the_out_of_range_flag_is_dropped_only_while_report_capacity_cannot_record_it(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    """DEC-148 item 7. ReportCapacity refuses any flag until U07 (its own test says so). The figure
    must still be stored, so the use case passes the flag first and, when that is refused for the
    flag alone, passes the same figure without it. When U07 lands the first call succeeds and this
    test is changed to expect one command."""
    await _one_reporter_one_prompt(uow_factory, neo4j_driver, seed_service)
    rig = Rig(uow_factory, neo4j_driver)
    await rig.say("40", bst(10, 12))
    await rig.say("40", bst(10, 13))

    assert [c.flag for c in rig.reports.commands] == [ReportFlagReason.OUT_OF_RANGE_TWICE, None]
    assert rig.reports.commands[0].idempotency_key == rig.reports.commands[1].idempotency_key
    assert (await _latest(uow_factory)).value == 40


# --- what is stored and what is not --------------------------------------------------------------


async def test_no_audit_entry_or_message_record_holds_the_phone_hash_or_the_text(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _one_reporter_one_prompt(uow_factory, neo4j_driver, seed_service)
    rig = Rig(uow_factory, neo4j_driver)
    typed = "hello there xq7"
    await rig.say(typed, bst(10, 5))
    await rig.say("4", bst(10, 12))
    await rig.say("40", bst(10, 13))

    audits = await _handle_audits(uow_factory)
    assert len(audits) == 3
    for record in audits:
        entry_text = canonical_entry_json(record.entry)
        assert PHONE not in entry_text
        assert typed not in entry_text
        assert record.entry.snapshot is not None
        assert set(record.entry.snapshot) == {"outcome", "items", "messages"}
        assert record.entry.actor.role is Role.REPORTER

    async def work(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        result = await tx.run(
            "MATCH (n) WHERE any(l IN labels(n) WHERE l IN "
            "['AuditEvent', 'Snapshot', 'Communication', 'OutboxMessage']) "
            "RETURN properties(n) AS props"
        )
        return await result.data()

    for row in await read_tx(neo4j_driver, work):
        text = repr(row["props"])
        assert PHONE not in text
        assert typed not in text


async def test_the_typed_text_is_not_stored_anywhere(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _one_reporter_one_prompt(uow_factory, neo4j_driver, seed_service)
    rig = Rig(uow_factory, neo4j_driver)
    typed = "hello there xq7"
    await rig.say(typed, bst(10, 5))

    async def work(tx: AsyncManagedTransaction) -> int:
        result = await tx.run("MATCH (n) RETURN properties(n) AS props")
        return sum(typed in repr(row["props"]) for row in await result.data())

    assert await read_tx(neo4j_driver, work) == 0
    assert await count_nodes(neo4j_driver, "AuditEvent") >= 1


async def test_the_command_carries_no_tenant_and_the_result_has_no_message_text() -> None:
    """DEC-130 to DEC-131: the tenant is bound at the edge from the called number. It is never a
    field of this command, so it cannot be taken from the message."""
    assert [f.name for f in dataclasses.fields(HandleInboundTextCommand)] == [
        "idempotency_key",
        "from_phone_hash",
        "text",
        "received_at",
    ]
    assert [f.name for f in dataclasses.fields(HandleInboundTextResult)] == [
        "outcome",
        "service_ids",
        "replayed",
    ]
