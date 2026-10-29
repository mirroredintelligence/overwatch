"""Integration tests for grouped prompts (U04), on the real Neo4j.

One phone looks after several services. When their prompts are due within GROUP_WINDOW of each
other, the phone gets one C9 text, lettered in name order, instead of one text each. U05 reads the
stored record to know which service a letter means, so what is stored is pinned here: one C9
Communication per grouped service, all with the same send time and text, and the text holds
"A) Name " for each letter.

Clock: Friday 23 October 2026. UCR East and UCR West both open 08:00 to 20:00 and report every
2 hours, so both are due at 10:00 London (09:00 UTC, BST). Synthetic values only: no patient data and
no real phone number (the phone hash is a made-up 64-character hex string).
"""

import dataclasses
import json
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
from diucs.application.actor import Actor
from diucs.application.ports.outbound.outbox import OutboxMessage
from diucs.application.ports.outbound.tokens import LinkTokenRepository, LinkTokenService
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.send_prompts import (
    SendPromptCommand,
    SendPrompts,
    SendPromptResult,
)
from diucs.application.work import ScheduledWork, WorkKind
from diucs.domain.codes import (
    Cadence,
    Channel,
    Measure,
    PractitionerRoleCode,
    ReportSource,
    ReportType,
    Role,
    ServiceCategory,
)
from diucs.domain.errors import Conflict
from diucs.domain.messages.privacy_guard import find_patient_data
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.flags import SERVICE_FLAG_SUSPENDED, ServiceFlag
from diucs.domain.model.people import Practitioner, PractitionerRole
from diucs.domain.model.service import AvailableTime, ServiceProfile
from tests.support.neo4j import count_nodes, read_tx

Seed = Callable[..., Awaitable[None]]

pytestmark = pytest.mark.asyncio(loop_scope="session")

SECRET = b"link-token-test-secret-0123456789abcdef"
TENANT = "tenant-a"
PHONE = "ab" * 32  # the prompt's "ph-456": the person repository refuses anything but 64 hex
OTHER_PHONE = "cd" * 32
DUE = datetime(2026, 10, 23, 9, 0, tzinfo=UTC)  # 10:00 BST

SYSTEM_ACTOR = Actor(
    role=Role.OWNER, practitioner_id=None, device_id=None, channel="worker", service_ids=frozenset()
)

COUNTED_LABELS = ("Communication", "LinkToken", "ScheduledWork", "OutboxMessage", "AuditEvent")


def _london(hour: int, minute: int) -> datetime:
    """A Friday 23 October 2026 London (BST) wall time as a UTC instant."""
    return datetime(2026, 10, 23, hour, minute, tzinfo=UTC) - timedelta(hours=1)


def _service(
    service_id: str,
    name: str,
    start: time = time(8, 0),
    channel: Channel = Channel.TEXT,
    **changes: Any,
) -> ServiceProfile:
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
        available_times=(AvailableTime.every_day(start, time(20, 0)),),
        channel=channel,
        limited_level_percent=80,
    )
    return dataclasses.replace(profile, **changes)


WEST = _service("ucr-west", "UCR West")
EAST = _service("ucr-east", "UCR East")
NORTH = _service("ucr-north", "UCR North")

FIGURES = {"ucr-west": 3, "ucr-east": 1, "ucr-north": 5}


def _role(
    service_id: str, practitioner: str = "prac-1", channel: Channel = Channel.TEXT, number: int = 1
) -> PractitionerRole:
    return PractitionerRole(
        id=f"role-{service_id}-{number}",
        practitioner_id=practitioner,
        service_id=service_id,
        code=PractitionerRoleCode.DUTY_MANAGER,
        active=True,
        channel=channel,
        period_start=datetime(2026, 1, 1, tzinfo=UTC),
    )


async def _seed_people(
    factory: UnitOfWorkFactory,
    practitioners: tuple[Practitioner, ...],
    roles: tuple[PractitionerRole, ...],
) -> None:
    async with factory() as uow:
        for practitioner in practitioners:
            await uow.people.save_practitioner(practitioner)
        for role in roles:
            await uow.people.save_role(role)
        await uow.commit()


async def _seed_report(
    factory: UnitOfWorkFactory,
    service_id: str,
    value: int | None = None,
    effective_at: datetime = datetime(2026, 10, 23, 7, 15, tzinfo=UTC),
) -> None:
    async with factory() as uow:
        await uow.capacity.add(
            CapacityReport(
                id=f"report-{service_id}",
                service_id=service_id,
                value=FIGURES[service_id] if value is None else value,
                measure=Measure.REFERRALS_ACCEPTABLE,
                effective_at=effective_at,
                source=ReportSource.TEXT,
                report_type=ReportType.NUMBER,
            )
        )
        await uow.commit()


async def _seed_phone(
    factory: UnitOfWorkFactory,
    seed_service: Seed,
    *profiles: ServiceProfile,
    reports: bool = True,
) -> None:
    """The phone PHONE reports for every profile given. Each has a figure unless reports is off."""
    await seed_service(*profiles)
    await _seed_people(
        factory,
        (Practitioner(id="prac-1", active=True, display_name="Reporter 1", phone_hash=PHONE),),
        tuple(_role(p.id, channel=p.channel) for p in profiles),
    )
    if reports:
        for profile in profiles:
            await _seed_report(factory, profile.id)


def _rig(
    factory: UnitOfWorkFactory, driver: AsyncDriver, now: datetime = DUE
) -> tuple[SendPrompts, FixedClock]:
    clock = FixedClock(now)

    def tokens(repo: LinkTokenRepository) -> LinkTokenService:
        return LinkTokenService(repo, FixedSecretStore({"link-token": SECRET}), clock)

    use_case = SendPrompts(
        factory,
        clock,
        SequentialIds(),
        DriverIdempotencyStore(driver),
        tokens,
        "diucs.example",
        AesGcmContentSealer(FixedSecretStore({"link-token": SECRET})),
        TENANT,
    )
    return use_case, clock


def _command(
    service_id: str, due_at: datetime = DUE, actor: Actor = SYSTEM_ACTOR
) -> SendPromptCommand:
    return SendPromptCommand(
        idempotency_key=f"prompt:{service_id}:{due_at.isoformat()}",
        actor=actor,
        service_id=service_id,
        due_at=due_at,
    )


async def _outbox(factory: UnitOfWorkFactory) -> list[OutboxMessage]:
    async with factory() as uow:
        return await uow.outbox.pending(limit=1000)


def _sent(messages: list[OutboxMessage]) -> list[OutboxMessage]:
    return [m for m in messages if m.event_type == "SendMessage"]


def _opened(message: OutboxMessage) -> dict[str, Any]:
    sealer = AesGcmContentSealer(FixedSecretStore({"link-token": SECRET}))
    opened: dict[str, Any] = json.loads(
        sealer.unseal(
            message.payload["sealed_content"],
            message_id=message.id,
            tenant_id=TENANT,
            recipient_role_id=message.payload["recipient_role_id"],
        )
    )
    return opened


async def _works(
    factory: UnitOfWorkFactory, about_id: str, kind: WorkKind | None = None
) -> list[ScheduledWork]:
    async with factory() as uow:
        return await uow.scheduled_work.for_about(about_id, kind)


async def _counts(driver: AsyncDriver) -> dict[str, int]:
    return {label: await count_nodes(driver, label) for label in COUNTED_LABELS}


async def _communications(driver: AsyncDriver) -> list[dict[str, Any]]:
    """Every stored Communication with the service it is about, its recipient role, message id,
    status, text and send time, in service order."""

    async def work(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        result = await tx.run(
            "MATCH (c:Communication) OPTIONAL MATCH (c)-[:TOPIC]->(t:Concept) "
            "OPTIONAL MATCH (c)-[:RECIPIENT]->(r:PractitionerRole) "
            "OPTIONAL MATCH (c)-[:ABOUT]->(s:HealthcareService) "
            "RETURN c.id AS id, c.payloadText AS text, c.deliveryStatus AS status, "
            "toString(c.sent) AS sent, t.code AS messageId, r.id AS role, s.id AS service "
            "ORDER BY s.id, c.id"
        )
        return await result.data()

    return await read_tx(driver, work)


def _by_service(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {row["service"]: row for row in rows}


# --- 1. one C9, in name order ------------------------------------------------------------------


async def test_a_phone_with_two_services_due_together_gets_one_c9_in_name_order(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_phone(uow_factory, seed_service, WEST, EAST)
    use_case, _ = _rig(uow_factory, neo4j_driver)

    result = await use_case.execute(_command("ucr-west"))

    [message] = _sent(await _outbox(uow_factory))
    text = _opened(message)["text"]
    assert text == (
        "DIUCS: 2 services need an update by 10:30. A) UCR East 1. B) UCR West 3. "
        "Reply Y if both right, or A 2, or B 4."
    )
    assert message.payload["message_id"] == "C9"
    assert result.sent is True
    assert result.skipped_reason is None
    assert result.grouped_service_ids == ("ucr-east", "ucr-west")
    assert find_patient_data(text) == []


# --- 2. what is stored, as U05 reads it --------------------------------------------------------


async def test_one_c9_communication_is_stored_for_each_service_and_only_letter_a_is_sent(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_phone(uow_factory, seed_service, WEST, EAST)
    use_case, _ = _rig(uow_factory, neo4j_driver)

    result = await use_case.execute(_command("ucr-west"))

    rows = _by_service(await _communications(neo4j_driver))
    assert set(rows) == {"ucr-east", "ucr-west"}
    east, west = rows["ucr-east"], rows["ucr-west"]
    assert east["messageId"] == west["messageId"] == "C9"
    # Same text and send time: U05 finds the group by them (lesson L153).
    assert east["text"] == west["text"]
    assert east["sent"] == west["sent"]
    assert "A) UCR East " in east["text"]
    assert "B) UCR West " in west["text"]
    # Each is addressed to the role this phone holds for that service.
    assert east["role"] == "role-ucr-east-1"
    assert west["role"] == "role-ucr-west-1"
    # Only letter A's is sent.
    assert east["status"] == "queued"
    assert west["status"] == "grouped"
    [message] = _sent(await _outbox(uow_factory))
    assert message.payload["communication_id"] == east["id"]
    assert message.payload["recipient_role_id"] == "role-ucr-east-1"
    assert await count_nodes(neo4j_driver, "Communication") == 2
    # The result is about the service that was asked for.
    assert result.communication_ids == (west["id"],)


async def test_no_link_is_issued_for_a_grouped_prompt(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    # C9 has no link field, so there is no one-time token to store.
    await _seed_phone(uow_factory, seed_service, WEST, EAST)
    use_case, _ = _rig(uow_factory, neo4j_driver)

    await use_case.execute(_command("ucr-west"))

    assert await count_nodes(neo4j_driver, "LinkToken") == 0


# --- 3. each service has its own ladder and next prompt ----------------------------------------


async def test_each_grouped_service_has_its_own_ladder_and_next_prompt(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_phone(uow_factory, seed_service, WEST, EAST)
    use_case, _ = _rig(uow_factory, neo4j_driver)

    await use_case.execute(_command("ucr-west"))

    rows = _by_service(await _communications(neo4j_driver))
    for service_id in ("ucr-east", "ucr-west"):
        # A ladder belongs to the communication the reporter got (DEC-115 item 16).
        communication_id = rows[service_id]["id"]
        ladder = await _works(uow_factory, communication_id)
        assert sorted((w.kind.value, w.due_at) for w in ladder) == sorted(
            [
                (WorkKind.REMINDER.value, _london(10, 30)),
                (WorkKind.PHONE_TASK.value, _london(11, 0)),
                (WorkKind.ESCALATE_TO_LEAD.value, _london(11, 30)),
            ]
        )
        [following] = await _works(uow_factory, service_id, WorkKind.PROMPT_DUE)
        assert following.due_at == _london(12, 0)
    # Three steps and a next prompt for each service, and nothing else.
    assert await count_nodes(neo4j_driver, "ScheduledWork") == 8


# --- 4. the other service's own prompt does nothing --------------------------------------------


async def test_the_other_grouped_services_own_prompt_is_a_replay_and_writes_nothing(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_phone(uow_factory, seed_service, WEST, EAST)
    use_case, _ = _rig(uow_factory, neo4j_driver)
    await use_case.execute(_command("ucr-west"))
    before = await _counts(neo4j_driver)
    rows = _by_service(await _communications(neo4j_driver))

    result = await use_case.execute(_command("ucr-east"))

    assert result.replayed is True
    assert result.sent is True
    assert result.communication_ids == (rows["ucr-east"]["id"],)
    assert result.grouped_service_ids == ("ucr-east", "ucr-west")
    assert await _counts(neo4j_driver) == before


async def test_a_grouped_services_key_cannot_be_reused_by_another_actor(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    # The record stored for the other service has the fingerprint of its own command (DEC-104).
    await _seed_phone(uow_factory, seed_service, WEST, EAST)
    use_case, _ = _rig(uow_factory, neo4j_driver)
    await use_case.execute(_command("ucr-west"))
    stranger = Actor(
        role=Role.OWNER,
        practitioner_id="prac-9",
        device_id=None,
        channel="worker",
        service_ids=frozenset(),
    )

    with pytest.raises(Conflict):
        await use_case.execute(_command("ucr-east", actor=stranger))


async def test_the_earlier_services_prompt_can_come_second_and_is_a_replay(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    # East is due at 10:00, West at 10:05. West's job runs first (East's was late): the group is
    # still sent once, and East's own job, when it runs, does nothing.
    await _seed_phone(uow_factory, seed_service, WEST, _service("ucr-east", "UCR East", time(8, 0)))
    async with uow_factory() as uow:
        await uow.services.save(_service("ucr-west", "UCR West", time(8, 5)))
        await uow.commit()
    use_case, clock = _rig(uow_factory, neo4j_driver, _london(10, 5))

    await use_case.execute(_command("ucr-west", _london(10, 5)))
    clock.set(_london(10, 6))
    result = await use_case.execute(_command("ucr-east", _london(10, 0)))

    assert result.replayed is True
    assert await count_nodes(neo4j_driver, "Communication") == 2
    assert len(_sent(await _outbox(uow_factory))) == 1


# --- 5. a service due outside the window is prompted on its own --------------------------------


async def test_a_service_due_twenty_minutes_later_gets_its_own_prompt(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_phone(
        uow_factory, seed_service, WEST, _service("ucr-east", "UCR East", time(8, 20))
    )
    use_case, clock = _rig(uow_factory, neo4j_driver)

    first = await use_case.execute(_command("ucr-west", _london(10, 0)))
    clock.set(_london(10, 20))
    second = await use_case.execute(_command("ucr-east", _london(10, 20)))

    assert first.replayed is False and second.replayed is False
    assert first.grouped_service_ids == () and second.grouped_service_ids == ()
    rows = _by_service(await _communications(neo4j_driver))
    assert rows["ucr-west"]["messageId"] == rows["ucr-east"]["messageId"] == "C1"
    assert {rows["ucr-west"]["status"], rows["ucr-east"]["status"]} == {"queued"}
    assert len(_sent(await _outbox(uow_factory))) == 2


@pytest.mark.parametrize(
    ("start", "grouped"),
    [(time(8, 9), True), (time(8, 10), False)],
    ids=["nine minutes", "ten minutes"],
)
async def test_the_window_is_less_than_ten_minutes_after_the_first_due_time(
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    seed_service: Seed,
    start: time,
    grouped: bool,
) -> None:
    await _seed_phone(uow_factory, seed_service, WEST, _service("ucr-east", "UCR East", start))
    use_case, _ = _rig(uow_factory, neo4j_driver)

    result = await use_case.execute(_command("ucr-west", _london(10, 0)))

    assert (result.grouped_service_ids != ()) is grouped


async def test_the_reply_by_is_the_earliest_in_the_group(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    # West is due at 10:05 but East at 10:00, so the group must be answered by 10:30, not 10:35.
    await _seed_phone(uow_factory, seed_service, _service("ucr-west", "UCR West", time(8, 5)), EAST)
    use_case, _ = _rig(uow_factory, neo4j_driver, _london(10, 5))

    await use_case.execute(_command("ucr-west", _london(10, 5)))

    [message] = _sent(await _outbox(uow_factory))
    assert "need an update by 10:30." in _opened(message)["text"]


# --- 6. three services ------------------------------------------------------------------------


async def test_three_services_due_together_are_lettered_a_b_c_in_name_order(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_phone(uow_factory, seed_service, WEST, EAST, NORTH)
    use_case, _ = _rig(uow_factory, neo4j_driver)

    result = await use_case.execute(_command("ucr-north"))

    [message] = _sent(await _outbox(uow_factory))
    assert _opened(message)["text"] == (
        "DIUCS: 3 services need an update by 10:30. A) UCR East 1. B) UCR North 5. "
        "C) UCR West 3. Reply Y if all right, or A 2, or B 6."
    )
    assert result.grouped_service_ids == ("ucr-east", "ucr-north", "ucr-west")
    rows = await _communications(neo4j_driver)
    assert sorted(row["status"] for row in rows) == ["grouped", "grouped", "queued"]
    for other in ("ucr-east", "ucr-west"):
        assert (await use_case.execute(_command(other))).replayed is True
    assert len(_sent(await _outbox(uow_factory))) == 1


# --- 7. only the same channel is grouped ------------------------------------------------------


async def test_an_email_service_on_the_same_phone_is_not_grouped(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_phone(
        uow_factory, seed_service, WEST, _service("ucr-east", "UCR East", channel=Channel.EMAIL)
    )
    use_case, _ = _rig(uow_factory, neo4j_driver)

    west = await use_case.execute(_command("ucr-west"))
    east = await use_case.execute(_command("ucr-east"))

    assert west.grouped_service_ids == () and east.grouped_service_ids == ()
    assert east.replayed is False
    rows = _by_service(await _communications(neo4j_driver))
    assert rows["ucr-west"]["messageId"] == rows["ucr-east"]["messageId"] == "C1"
    assert len(_sent(await _outbox(uow_factory))) == 2


# --- what makes a service ineligible for the group --------------------------------------------


async def test_a_service_with_no_figure_yet_is_not_grouped(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    # C9 shows a whole number for every service, and "Y if both right" means nothing for a service
    # with no figure (DEC-156 item 3), so it gets its own first prompt (C2).
    await _seed_phone(uow_factory, seed_service, WEST, EAST, reports=False)
    await _seed_report(uow_factory, "ucr-west")
    use_case, _ = _rig(uow_factory, neo4j_driver)

    west = await use_case.execute(_command("ucr-west"))
    east = await use_case.execute(_command("ucr-east"))

    assert west.grouped_service_ids == () and east.grouped_service_ids == ()
    rows = _by_service(await _communications(neo4j_driver))
    assert rows["ucr-west"]["messageId"] == "C1"
    assert rows["ucr-east"]["messageId"] == "C2"


async def test_the_triggering_service_with_no_figure_is_not_grouped_either(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_phone(uow_factory, seed_service, WEST, EAST, reports=False)
    await _seed_report(uow_factory, "ucr-east")
    use_case, _ = _rig(uow_factory, neo4j_driver)

    west = await use_case.execute(_command("ucr-west"))

    assert west.grouped_service_ids == ()
    assert _by_service(await _communications(neo4j_driver))["ucr-west"]["messageId"] == "C2"


@pytest.mark.parametrize("why", ["inactive", "suspended"])
async def test_an_inactive_or_suspended_service_is_not_grouped(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed, why: str
) -> None:
    east = dataclasses.replace(EAST, active=False) if why == "inactive" else EAST
    await seed_service(WEST, east)
    await _seed_people(
        uow_factory,
        (Practitioner(id="prac-1", active=True, display_name="Reporter 1", phone_hash=PHONE),),
        (_role("ucr-west"), _role("ucr-east")),
    )
    await _seed_report(uow_factory, "ucr-west")
    await _seed_report(uow_factory, "ucr-east")
    if why == "suspended":
        async with uow_factory() as uow:
            await uow.flags.set_service_flag(
                ServiceFlag(
                    service_id="ucr-east",
                    code=SERVICE_FLAG_SUSPENDED,
                    active=True,
                    reason="staffing",
                    actor_id="prac-lead-1",
                    at=DUE - timedelta(hours=3),
                )
            )
            await uow.commit()
    use_case, _ = _rig(uow_factory, neo4j_driver)

    west = await use_case.execute(_command("ucr-west"))
    east_result = await use_case.execute(_command("ucr-east"))

    assert west.grouped_service_ids == ()
    assert west.sent is True
    assert east_result.sent is False  # its own prompt is skipped, as before
    assert [r["messageId"] for r in await _communications(neo4j_driver)] == ["C1"]


async def test_a_service_already_prompted_is_not_grouped_again(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    # West was prompted alone at 10:00, because East had no figure then. East's figure arrives and
    # East is due at 10:05: West must not be prompted a second time inside a group.
    east = _service("ucr-east", "UCR East", time(8, 5))
    await _seed_phone(uow_factory, seed_service, WEST, east, reports=False)
    await _seed_report(uow_factory, "ucr-west")
    use_case, clock = _rig(uow_factory, neo4j_driver)
    await use_case.execute(_command("ucr-west", _london(10, 0)))
    await _seed_report(uow_factory, "ucr-east")
    clock.set(_london(10, 5))

    result = await use_case.execute(_command("ucr-east", _london(10, 5)))

    assert result.grouped_service_ids == ()
    rows = await _communications(neo4j_driver)
    assert [r["messageId"] for r in rows] == ["C1", "C1"]
    assert len(_sent(await _outbox(uow_factory))) == 2


async def test_services_whose_names_collide_are_prompted_separately_not_refused(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    # Letters cannot tell two services with one name apart, and a reply must never land on the
    # wrong one. The prompt is not lost: each is sent on its own.
    twin = _service("ucr-east", "UCR West")
    await _seed_phone(uow_factory, seed_service, WEST, twin)
    use_case, _ = _rig(uow_factory, neo4j_driver)

    west = await use_case.execute(_command("ucr-west"))
    east = await use_case.execute(_command("ucr-east"))

    assert west.sent and east.sent
    assert west.grouped_service_ids == () and east.grouped_service_ids == ()
    assert [r["messageId"] for r in await _communications(neo4j_driver)] == ["C1", "C1"]


# --- a service's other reporters still get their prompt ---------------------------------------


async def test_a_grouped_services_other_reporter_on_another_phone_still_gets_a_prompt(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    # East's own prompt will now be a replay, so the reporter on the other phone must be prompted
    # now, on her own, or East's second reporter would never be asked.
    await _seed_phone(uow_factory, seed_service, WEST, EAST)
    await _seed_people(
        uow_factory,
        (
            Practitioner(
                id="prac-2", active=True, display_name="Reporter 2", phone_hash=OTHER_PHONE
            ),
        ),
        (_role("ucr-east", practitioner="prac-2", number=2),),
    )
    use_case, _ = _rig(uow_factory, neo4j_driver)

    await use_case.execute(_command("ucr-west"))

    rows = await _communications(neo4j_driver)
    assert sorted((r["service"], r["role"], r["messageId"], r["status"]) for r in rows) == [
        ("ucr-east", "role-ucr-east-1", "C9", "queued"),
        ("ucr-east", "role-ucr-east-2", "C1", "queued"),
        ("ucr-west", "role-ucr-west-1", "C9", "grouped"),
    ]
    assert len(_sent(await _outbox(uow_factory))) == 2
    # The single prompt has its own link; the group has none.
    assert await count_nodes(neo4j_driver, "LinkToken") == 1
    # That reporter's prompt has its own ladder too, and East's chain goes on once.
    second = next(r for r in rows if r["role"] == "role-ucr-east-2")
    assert len(await _works(uow_factory, second["id"])) == 3
    assert len(await _works(uow_factory, "ucr-east", WorkKind.PROMPT_DUE)) == 1


async def test_a_phone_that_is_not_the_one_asked_is_not_grouped_with_the_others(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    # Two reporters for West: one phone also holds East, the other holds West alone. Only the first
    # phone gets a C9.
    await _seed_phone(uow_factory, seed_service, WEST, EAST)
    await _seed_people(
        uow_factory,
        (
            Practitioner(
                id="prac-2", active=True, display_name="Reporter 2", phone_hash=OTHER_PHONE
            ),
        ),
        (_role("ucr-west", practitioner="prac-2", number=2),),
    )
    use_case, _ = _rig(uow_factory, neo4j_driver)

    await use_case.execute(_command("ucr-west"))

    rows = await _communications(neo4j_driver)
    assert sorted((r["service"], r["role"], r["messageId"]) for r in rows) == [
        ("ucr-east", "role-ucr-east-1", "C9"),
        ("ucr-west", "role-ucr-west-1", "C9"),
        ("ucr-west", "role-ucr-west-2", "C1"),
    ]


# --- one unit of work -------------------------------------------------------------------------


class _FailingAudit:
    def __init__(self, inner: Any) -> None:
        self._inner = inner

    async def append(self, entry: Any) -> None:
        raise RuntimeError("audit write failed")

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class _FailingAuditUnitOfWork:
    def __init__(self, inner: Any) -> None:
        self._inner = inner

    @property
    def audit(self) -> _FailingAudit:
        return _FailingAudit(self._inner.audit)

    async def __aenter__(self) -> _FailingAuditUnitOfWork:
        await self._inner.__aenter__()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self._inner.__aexit__(*exc)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


async def test_a_failure_after_the_writes_leaves_no_trace_of_the_group(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    # The audit append is the last write. Every grouped write, and the other service's stored
    # result, must go with it: the other service's own job must then still send its own prompt.
    await _seed_phone(uow_factory, seed_service, WEST, EAST)
    before = await _counts(neo4j_driver)

    def failing() -> Any:
        return _FailingAuditUnitOfWork(uow_factory())

    use_case, _ = _rig(failing, neo4j_driver)  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="audit write failed"):
        await use_case.execute(_command("ucr-west"))

    assert await _counts(neo4j_driver) == before
    again, _ = _rig(uow_factory, neo4j_driver)
    result = await again.execute(_command("ucr-east"))
    assert result.replayed is False
    assert result.grouped_service_ids == ("ucr-east", "ucr-west")


async def test_the_audit_entry_names_every_service_prompted_together(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_phone(uow_factory, seed_service, WEST, EAST)
    use_case, _ = _rig(uow_factory, neo4j_driver)

    await use_case.execute(_command("ucr-west"))

    async with uow_factory() as uow:
        records = await uow.audit.records()
    [record] = records
    assert record.entry.use_case == "SendPrompts"
    assert {"ucr-east", "ucr-west"} <= set(record.entry.entity_ids)


async def test_the_result_type_has_the_grouped_field_empty_by_default() -> None:
    assert SendPromptResult(True, ("c",), None).grouped_service_ids == ()
