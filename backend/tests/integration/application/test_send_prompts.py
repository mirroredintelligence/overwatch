"""Integration tests for SendPrompts and the scheduling helpers (U03), on the real Neo4j.

Seeds go through committed units of work; assertions read back through a fresh unit of work or the
harness helpers. Synthetic values only: no patient data, no real phone number.

Clock: Friday 23 October 2026. The prompt is due at 10:00 London (09:00 UTC, BST). UCR West opens
08:00 to 20:00 every day and reports every 2 hours.
"""

import dataclasses
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, time, timedelta
from typing import Any

import pytest
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.idempotency_store import DriverIdempotencyStore
from diucs.adapters.outbound.graph_store.link_token_repository import Neo4jLinkTokenRepository
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.application.actor import Actor
from diucs.application.ports.outbound.outbox import OutboxMessage
from diucs.application.ports.outbound.tokens import LinkTokenRepository, LinkTokenService
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.scheduling import cancel_work, schedule_work
from diucs.application.use_cases.send_prompts import (
    SendPromptCommand,
    SendPromptResult,
    SendPrompts,
)
from diucs.application.work import CANCELLED, SCHEDULED, ScheduledWork, WorkKind
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
from diucs.domain.errors import NotFound, ValidationFailed
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.flags import SERVICE_FLAG_SUSPENDED, ServiceFlag
from diucs.domain.model.people import Practitioner, PractitionerRole
from diucs.domain.model.service import AvailableTime, ServiceProfile
from tests.support.neo4j import count_nodes, read_tx

Seed = Callable[..., Awaitable[None]]

pytestmark = pytest.mark.asyncio(loop_scope="session")

SECRET = b"link-token-test-secret-0123456789abcdef"
LINK_BASE = "diucs.example"
DUE = datetime(2026, 10, 23, 9, 0, tzinfo=UTC)  # 10:00 BST
PHONE_HASH_1 = "ab" * 32
PHONE_HASH_2 = "cd" * 32

SYSTEM_ACTOR = Actor(
    role=Role.OWNER, practitioner_id=None, device_id=None, channel="worker", service_ids=frozenset()
)

UCR_WEST = ServiceProfile(
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


def _practitioner(number: int, phone_hash: str | None) -> Practitioner:
    return Practitioner(
        id=f"prac-{number}", active=True, display_name=f"Reporter {number}", phone_hash=phone_hash
    )


def _role(number: int, **changes: Any) -> PractitionerRole:
    role = PractitionerRole(
        id=f"role-{number}",
        practitioner_id=f"prac-{number}",
        service_id="ucr-west",
        code=PractitionerRoleCode.DUTY_MANAGER,
        active=True,
        channel=Channel.TEXT,
        period_start=datetime(2026, 1, 1, tzinfo=UTC),
    )
    return dataclasses.replace(role, **changes)


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


async def _seed_report(factory: UnitOfWorkFactory, value: int = 3) -> None:
    async with factory() as uow:
        await uow.capacity.add(
            CapacityReport(
                id="report-1",
                service_id="ucr-west",
                value=value,
                measure=Measure.REFERRALS_ACCEPTABLE,
                effective_at=datetime(2026, 10, 23, 7, 15, tzinfo=UTC),  # 08:15 BST
                source=ReportSource.TEXT,
                report_type=ReportType.NUMBER,
            )
        )
        await uow.commit()


async def _seed_one_reporter(factory: UnitOfWorkFactory, seed_service: Seed) -> None:
    await seed_service(UCR_WEST)
    await _seed_people(factory, (_practitioner(1, PHONE_HASH_1),), (_role(1),))


def _rig(
    factory: UnitOfWorkFactory,
    driver: AsyncDriver,
    now: datetime = DUE,
    link_base: str = LINK_BASE,
) -> tuple[SendPrompts, FixedClock]:
    clock = FixedClock(now)

    def tokens(repo: LinkTokenRepository) -> LinkTokenService:
        return LinkTokenService(repo, FixedSecretStore({"link-token": SECRET}), clock)

    use_case = SendPrompts(
        factory, clock, SequentialIds(), DriverIdempotencyStore(driver), tokens, link_base
    )
    return use_case, clock


def _command(due_at: datetime = DUE, service_id: str = "ucr-west") -> SendPromptCommand:
    return SendPromptCommand(
        idempotency_key=f"prompt:{service_id}:{due_at.isoformat()}",
        actor=SYSTEM_ACTOR,
        service_id=service_id,
        due_at=due_at,
    )


async def _outbox(factory: UnitOfWorkFactory) -> list[OutboxMessage]:
    async with factory() as uow:
        return await uow.outbox.pending(limit=1000)


async def _work_about(factory: UnitOfWorkFactory, about_id: str) -> list[ScheduledWork]:
    async with factory() as uow:
        return await uow.scheduled_work.for_about(about_id)


async def _communication_nodes(driver: AsyncDriver) -> list[dict[str, Any]]:
    async def work(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        result = await tx.run(
            "MATCH (c:Communication) OPTIONAL MATCH (c)-[:TOPIC]->(t:Concept) "
            "OPTIONAL MATCH (c)-[:RECIPIENT]->(r:PractitionerRole) "
            "RETURN c.id AS id, c.payloadText AS text, c.deliveryStatus AS status, "
            "t.code AS messageId, r.id AS role ORDER BY c.id"
        )
        return await result.data()

    return await read_tx(driver, work)


async def _node_counts(driver: AsyncDriver) -> tuple[int, int, int]:
    return (
        await count_nodes(driver, "Communication"),
        await count_nodes(driver, "ScheduledWork"),
        await count_nodes(driver, "OutboxMessage"),
    )


def _london(hour: int, minute: int) -> datetime:
    """A Friday 23 October 2026 London (BST) wall time as a UTC instant."""
    return datetime(2026, 10, 23, hour, minute, tzinfo=UTC) - timedelta(hours=1)


async def test_c1_text_carries_the_figure_the_deadline_and_a_one_time_link(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_one_reporter(uow_factory, seed_service)
    await _seed_report(uow_factory)
    use_case, clock = _rig(uow_factory, neo4j_driver)

    result = await use_case.execute(_command())

    assert result.sent is True
    assert result.skipped_reason is None
    assert result.replayed is False
    assert len(result.communication_ids) == 1
    [row] = await _communication_nodes(neo4j_driver)
    assert row["id"] == result.communication_ids[0]
    assert row["messageId"] == "C1"
    assert row["status"] == "queued"
    assert row["role"] == "role-1"
    text = row["text"]
    assert text.startswith("DIUCS: UCR West. We have 3 referrals in the next 2 hrs (as of 08:15).")
    assert "By 10:30." in text
    match = re.search(rf"Confirm or update: {re.escape(LINK_BASE)}/(\S+) Or reply Y", text)
    assert match is not None
    token = match.group(1)

    def tokens(repo: LinkTokenRepository) -> LinkTokenService:
        return LinkTokenService(repo, FixedSecretStore({"link-token": SECRET}), clock)

    async def work(tx: AsyncManagedTransaction) -> Any:
        return await tokens(Neo4jLinkTokenRepository(tx)).resolve(token)

    record = await read_tx(neo4j_driver, work)
    assert record is not None
    assert record.expires_at == _london(10, 30)
    assert record.used_at is None
    assert record.phone_hash == PHONE_HASH_1
    assert record.about_id == result.communication_ids[0]

    async def link_props(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        return await (await tx.run("MATCH (t:LinkToken) RETURN properties(t) AS props")).data()

    [stored] = await read_tx(neo4j_driver, link_props)
    assert all(token not in str(value) for value in stored["props"].values())


async def test_the_ladder_and_the_next_prompt_are_scheduled(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_one_reporter(uow_factory, seed_service)
    await _seed_report(uow_factory)
    use_case, _ = _rig(uow_factory, neo4j_driver)

    result = await use_case.execute(_command())

    [communication_id] = result.communication_ids
    ladder = await _work_about(uow_factory, communication_id)
    assert [(w.kind, w.due_at, w.status) for w in ladder] == [
        (WorkKind.REMINDER, _london(10, 30), SCHEDULED),
        (WorkKind.PHONE_TASK, _london(11, 0), SCHEDULED),
        (WorkKind.ESCALATE_TO_LEAD, _london(11, 30), SCHEDULED),
    ]
    [next_prompt] = await _work_about(uow_factory, "ucr-west")
    assert (next_prompt.kind, next_prompt.due_at, next_prompt.status) == (
        WorkKind.PROMPT_DUE,
        _london(12, 0),
        SCHEDULED,
    )
    messages = [m for m in await _outbox(uow_factory) if m.event_type == "ScheduleWork"]
    assert len(messages) == 4
    assert {m.topic for m in messages} == {"scheduled.work"}
    by_work = {m.payload["work_id"]: m.payload for m in messages}
    for work in (*ladder, next_prompt):
        assert by_work[work.id] == {
            "work_id": work.id,
            "kind": work.kind.value,
            "about_id": work.about_id,
            "enqueue_at": work.due_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }


async def test_with_no_earlier_report_the_first_prompt_c2_is_sent(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_one_reporter(uow_factory, seed_service)
    use_case, _ = _rig(uow_factory, neo4j_driver)

    result = await use_case.execute(_command())

    assert result.sent is True
    [row] = await _communication_nodes(neo4j_driver)
    assert row["messageId"] == "C2"
    assert row["text"] == (
        "DIUCS: UCR West. How many referrals can you take in the next 2 hrs? "
        "Send a number (0 = closed). By 10:30."
    )


async def test_the_send_message_carries_the_role_and_the_channel_and_no_phone(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_one_reporter(uow_factory, seed_service)
    await _seed_report(uow_factory)
    use_case, _ = _rig(uow_factory, neo4j_driver)

    result = await use_case.execute(_command())

    [message] = [m for m in await _outbox(uow_factory) if m.event_type == "SendMessage"]
    assert message.topic == "messages.outbound"
    assert message.payload["communication_id"] == result.communication_ids[0]
    assert message.payload["message_id"] == "C1"
    assert message.payload["channel"] == "text"
    assert message.payload["recipient_role_id"] == "role-1"
    for outbox_message in await _outbox(uow_factory):
        rendered = repr(outbox_message.payload)
        assert PHONE_HASH_1 not in rendered
        assert not re.search(r"\b0?7\d{9}\b|\+44", rendered)


async def test_the_use_case_writes_one_audit_entry(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_one_reporter(uow_factory, seed_service)
    use_case, _ = _rig(uow_factory, neo4j_driver)

    result = await use_case.execute(_command())

    async with uow_factory() as uow:
        records = await uow.audit.records()
        chain_ok = await uow.audit.verify_chain()
    assert chain_ok is True
    [record] = records
    assert record.entry.use_case == "SendPrompts"
    assert record.entry.actor == SYSTEM_ACTOR
    assert record.entry.entity_ids == (*result.communication_ids, "ucr-west")
    assert record.entry.snapshot == {"due_at": DUE.isoformat(), "prompts": 1}
    assert record.entry.at == DUE


@pytest.mark.parametrize(
    ("reason_part", "due_at"),
    [("suspended", DUE), ("not active", DUE), ("out of hours", _london(21, 0))],
)
async def test_a_skipped_prompt_writes_nothing(
    reason_part: str,
    due_at: datetime,
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    seed_service: Seed,
) -> None:
    profile = (
        dataclasses.replace(UCR_WEST, active=False) if reason_part == "not active" else UCR_WEST
    )
    flags = ()
    if reason_part == "suspended":
        flags = (
            ServiceFlag(
                service_id="ucr-west",
                code=SERVICE_FLAG_SUSPENDED,
                active=True,
                reason="staffing",
                actor_id="prac-lead-1",
                at=DUE - timedelta(hours=3),
            ),
        )
    await seed_service(profile, flags=flags)
    await _seed_people(uow_factory, (_practitioner(1, PHONE_HASH_1),), (_role(1),))
    use_case, _ = _rig(uow_factory, neo4j_driver, now=due_at)

    result = await use_case.execute(_command(due_at))

    assert result.sent is False
    assert result.communication_ids == ()
    assert result.skipped_reason is not None
    assert reason_part in result.skipped_reason
    assert await _node_counts(neo4j_driver) == (0, 0, 0)
    assert await count_nodes(neo4j_driver, "LinkToken") == 0
    assert await count_nodes(neo4j_driver, "AuditEvent") == 0


async def test_a_lifted_suspension_does_not_skip_the_prompt(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    lifted = ServiceFlag(
        service_id="ucr-west",
        code=SERVICE_FLAG_SUSPENDED,
        active=False,
        reason="staffing",
        actor_id="prac-lead-1",
        at=DUE - timedelta(hours=3),
    )
    await seed_service(UCR_WEST, flags=(lifted,))
    await _seed_people(uow_factory, (_practitioner(1, PHONE_HASH_1),), (_role(1),))
    use_case, _ = _rig(uow_factory, neo4j_driver)

    assert (await use_case.execute(_command())).sent is True


async def test_a_prompt_after_its_reply_window_is_skipped(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_one_reporter(uow_factory, seed_service)
    use_case, _ = _rig(uow_factory, neo4j_driver, now=DUE + timedelta(minutes=30))

    result = await use_case.execute(_command())

    assert result.sent is False
    assert result.skipped_reason is not None
    assert "reply window" in result.skipped_reason
    assert await _node_counts(neo4j_driver) == (0, 0, 0)


async def test_a_prompt_one_second_before_its_reply_window_closes_is_sent(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_one_reporter(uow_factory, seed_service)
    use_case, _ = _rig(uow_factory, neo4j_driver, now=DUE + timedelta(minutes=29, seconds=59))

    assert (await use_case.execute(_command())).sent is True


async def test_two_reporter_roles_get_two_prompts_and_two_ladders(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)
    await _seed_people(
        uow_factory,
        (_practitioner(1, PHONE_HASH_1), _practitioner(2, PHONE_HASH_2)),
        (_role(1), _role(2, code=PractitionerRoleCode.COORDINATOR)),
    )
    use_case, _ = _rig(uow_factory, neo4j_driver)

    result = await use_case.execute(_command())

    assert len(result.communication_ids) == 2
    assert len(set(result.communication_ids)) == 2
    rows = await _communication_nodes(neo4j_driver)
    assert sorted(row["role"] for row in rows) == ["role-1", "role-2"]
    sends = [m for m in await _outbox(uow_factory) if m.event_type == "SendMessage"]
    assert sorted(m.payload["communication_id"] for m in sends) == sorted(result.communication_ids)
    assert await count_nodes(neo4j_driver, "LinkToken") == 2
    for communication_id in result.communication_ids:
        assert len(await _work_about(uow_factory, communication_id)) == 3
    assert len(await _work_about(uow_factory, "ucr-west")) == 1


async def test_cover_sends_the_prompt_to_the_cover_phone(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)
    covered = _role(1, covered_by_practitioner_id="prac-2", covered_until=DUE + timedelta(hours=4))
    await _seed_people(
        uow_factory,
        (_practitioner(1, PHONE_HASH_1), _practitioner(2, PHONE_HASH_2)),
        (covered,),
    )
    use_case, _ = _rig(uow_factory, neo4j_driver)

    result = await use_case.execute(_command())

    [communication_id] = result.communication_ids
    [row] = await _communication_nodes(neo4j_driver)
    assert row["id"] == communication_id
    assert row["role"] == "role-1"

    async def token_phones(tx: AsyncManagedTransaction) -> list[str]:
        rows = await (await tx.run("MATCH (t:LinkToken) RETURN t.phoneHash AS hash")).data()
        return [r["hash"] for r in rows]

    assert await read_tx(neo4j_driver, token_phones) == [PHONE_HASH_2]


async def test_a_reporter_with_no_phone_is_left_out_and_the_next_prompt_is_still_scheduled(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)
    await _seed_people(uow_factory, (_practitioner(1, None),), (_role(1),))
    use_case, _ = _rig(uow_factory, neo4j_driver)

    result = await use_case.execute(_command())

    assert result.sent is False
    assert result.communication_ids == ()
    assert result.skipped_reason is not None
    assert "no reporter" in result.skipped_reason
    assert await count_nodes(neo4j_driver, "Communication") == 0
    assert await count_nodes(neo4j_driver, "LinkToken") == 0
    [next_prompt] = await _work_about(uow_factory, "ucr-west")
    assert next_prompt.kind is WorkKind.PROMPT_DUE
    assert next_prompt.due_at == _london(12, 0)


async def test_a_reporter_with_no_phone_does_not_stop_the_other_reporter_being_prompted(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)
    await _seed_people(
        uow_factory,
        (_practitioner(1, None), _practitioner(2, PHONE_HASH_2)),
        (_role(1), _role(2, code=PractitionerRoleCode.COORDINATOR)),
    )
    use_case, _ = _rig(uow_factory, neo4j_driver)

    result = await use_case.execute(_command())

    assert result.sent is True
    [row] = await _communication_nodes(neo4j_driver)
    assert row["role"] == "role-2"


async def test_a_replay_of_the_same_due_time_changes_nothing(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_one_reporter(uow_factory, seed_service)
    use_case, _ = _rig(uow_factory, neo4j_driver)
    first = await use_case.execute(_command())
    counts = await _node_counts(neo4j_driver)
    tokens = await count_nodes(neo4j_driver, "LinkToken")

    replay = await use_case.execute(_command())

    assert replay == dataclasses.replace(first, replayed=True)
    assert await _node_counts(neo4j_driver) == counts
    assert await count_nodes(neo4j_driver, "LinkToken") == tokens


async def test_the_next_due_time_is_a_separate_prompt(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_one_reporter(uow_factory, seed_service)
    use_case, clock = _rig(uow_factory, neo4j_driver)
    await use_case.execute(_command())
    clock.set(DUE + timedelta(hours=2))

    second = await use_case.execute(_command(DUE + timedelta(hours=2)))

    assert second.sent is True
    assert second.replayed is False
    assert await count_nodes(neo4j_driver, "Communication") == 2


async def test_an_unknown_service_is_refused(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)
    use_case, _ = _rig(uow_factory, neo4j_driver)

    with pytest.raises(NotFound):
        await use_case.execute(_command(service_id="no-such-service"))


async def test_a_due_time_without_a_timezone_is_refused(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_one_reporter(uow_factory, seed_service)
    use_case, _ = _rig(uow_factory, neo4j_driver)
    naive = SendPromptCommand("key-naive", SYSTEM_ACTOR, "ucr-west", datetime(2026, 10, 23, 9, 0))

    with pytest.raises(ValidationFailed):
        await use_case.execute(naive)

    assert await _node_counts(neo4j_driver) == (0, 0, 0)


async def test_a_failure_part_way_leaves_nothing_behind(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_one_reporter(uow_factory, seed_service)
    clock = FixedClock(DUE)

    def failing_tokens(repo: LinkTokenRepository) -> LinkTokenService:
        # A secret store with no link-token secret: issuing the token fails after other writes.
        return LinkTokenService(repo, FixedSecretStore({}), clock)

    use_case = SendPrompts(
        uow_factory,
        clock,
        SequentialIds(),
        DriverIdempotencyStore(neo4j_driver),
        failing_tokens,
        LINK_BASE,
    )

    with pytest.raises(Exception):  # noqa: B017 - the exact error is the secret store's
        await use_case.execute(_command())

    assert await _node_counts(neo4j_driver) == (0, 0, 0)


async def test_schedule_work_writes_the_row_and_the_outbox_message(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver
) -> None:
    due = datetime(2026, 10, 23, 11, 0, tzinfo=UTC)
    async with uow_factory() as uow:
        work = await schedule_work(
            uow, SequentialIds("w"), kind=WorkKind.REMINDER, about_id="comm-1", due_at=due, now=DUE
        )
        await uow.commit()

    assert work.status == SCHEDULED
    assert work.sequence_number is None
    assert (work.kind, work.about_id, work.due_at) == (WorkKind.REMINDER, "comm-1", due)
    async with uow_factory() as uow:
        assert await uow.scheduled_work.get(work.id) == work
    [message] = await _outbox(uow_factory)
    assert (message.topic, message.event_type) == ("scheduled.work", "ScheduleWork")
    assert message.payload == {
        "work_id": work.id,
        "kind": "reminder",
        "about_id": "comm-1",
        "enqueue_at": "2026-10-23T11:00:00Z",
    }
    assert message.created_at == DUE


async def test_schedule_work_converts_a_london_due_time_to_the_same_instant(
    uow_factory: UnitOfWorkFactory,
) -> None:
    from zoneinfo import ZoneInfo

    # 01:30 on 2026-10-25 occurs twice. fold=1 is the second one (GMT), 02:30 UTC.
    due = datetime(2026, 10, 25, 1, 30, tzinfo=ZoneInfo("Europe/London"), fold=1)
    async with uow_factory() as uow:
        work = await schedule_work(
            uow, SequentialIds("w"), kind=WorkKind.REMINDER, about_id="comm-1", due_at=due, now=DUE
        )
        await uow.commit()

    assert work.due_at.astimezone(UTC) == datetime(2026, 10, 25, 1, 30, tzinfo=UTC)
    [message] = await _outbox(uow_factory)
    assert message.payload["enqueue_at"] == "2026-10-25T01:30:00Z"


async def test_schedule_work_refuses_a_naive_due_time(uow_factory: UnitOfWorkFactory) -> None:
    async with uow_factory() as uow:
        with pytest.raises(ValidationFailed):
            await schedule_work(
                uow,
                SequentialIds("w"),
                kind=WorkKind.REMINDER,
                about_id="comm-1",
                due_at=datetime(2026, 10, 23, 11, 0),
                now=DUE,
            )


async def test_cancel_work_marks_the_row_cancelled_and_queues_a_cancel(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver
) -> None:
    async with uow_factory() as uow:
        work = await schedule_work(
            uow,
            SequentialIds("w"),
            kind=WorkKind.BOOKING_EXPIRE,
            about_id="booking-1",
            due_at=DUE + timedelta(minutes=10),
            now=DUE,
        )
        await uow.commit()

    async with uow_factory() as uow:
        await cancel_work(uow, work, DUE + timedelta(minutes=1))
        await uow.commit()

    async with uow_factory() as uow:
        stored = await uow.scheduled_work.get(work.id)
    assert stored.status == CANCELLED
    assert (stored.kind, stored.about_id, stored.due_at) == (work.kind, work.about_id, work.due_at)
    cancels = [m for m in await _outbox(uow_factory) if m.event_type == "CancelWork"]
    assert len(cancels) == 1
    assert cancels[0].topic == "scheduled.work"
    assert cancels[0].payload == {"work_id": work.id}
    assert cancels[0].created_at == DUE + timedelta(minutes=1)


async def test_cancel_work_keeps_the_sequence_number_the_relay_stored(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver
) -> None:
    async with uow_factory() as uow:
        work = await schedule_work(
            uow, SequentialIds("w"), kind=WorkKind.REVERIFY, about_id="p-1", due_at=DUE, now=DUE
        )
        await uow.scheduled_work.save(dataclasses.replace(work, sequence_number=42))
        await uow.commit()

    async with uow_factory() as uow:
        await cancel_work(uow, work, DUE)  # a stale copy, without the sequence number
        await uow.commit()

    async with uow_factory() as uow:
        stored = await uow.scheduled_work.get(work.id)
    assert (stored.status, stored.sequence_number) == (CANCELLED, 42)


@pytest.mark.parametrize("status", ["done", "cancelled"])
async def test_cancel_work_does_nothing_for_work_that_is_not_scheduled(
    status: str, uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver
) -> None:
    async with uow_factory() as uow:
        work = await schedule_work(
            uow, SequentialIds("w"), kind=WorkKind.REVERIFY, about_id="p-1", due_at=DUE, now=DUE
        )
        await uow.scheduled_work.save(dataclasses.replace(work, status=status))
        await uow.commit()
    before = await count_nodes(neo4j_driver, "OutboxMessage")

    async with uow_factory() as uow:
        await cancel_work(uow, work, DUE)
        await uow.commit()

    async with uow_factory() as uow:
        assert (await uow.scheduled_work.get(work.id)).status == status
    assert await count_nodes(neo4j_driver, "OutboxMessage") == before


async def test_result_type_is_the_documented_shape() -> None:
    result = SendPromptResult(sent=False, communication_ids=(), skipped_reason="x")
    assert result.replayed is False


async def test_an_inactive_holder_is_left_out(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)
    gone = dataclasses.replace(_practitioner(1, PHONE_HASH_1), active=False)
    await _seed_people(uow_factory, (gone,), (_role(1),))
    use_case, _ = _rig(uow_factory, neo4j_driver)

    result = await use_case.execute(_command())

    assert result.sent is False
    assert await count_nodes(neo4j_driver, "Communication") == 0
    assert await count_nodes(neo4j_driver, "LinkToken") == 0


async def test_the_ladder_is_counted_in_real_minutes_across_the_autumn_clock_change(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    # 00:30 UTC on 2026-10-25 is 01:30 BST, the hour before the clocks go back. The reminder 30
    # minutes later is 01:00 UTC, which is 01:00 GMT on the wall clock: the same wall time as the
    # prompt's hour, so only an instant comparison keeps the order (lessons L4, L52).
    due = datetime(2026, 10, 25, 0, 30, tzinfo=UTC)
    early = dataclasses.replace(
        UCR_WEST, available_times=(AvailableTime.every_day(time(0, 0), time(20, 0)),)
    )
    await seed_service(early)
    await _seed_people(uow_factory, (_practitioner(1, PHONE_HASH_1),), (_role(1),))
    use_case, _ = _rig(uow_factory, neo4j_driver, now=due)

    result = await use_case.execute(_command(due))

    [communication_id] = result.communication_ids
    ladder = await _work_about(uow_factory, communication_id)
    assert [w.due_at for w in ladder] == [
        datetime(2026, 10, 25, 1, 0, tzinfo=UTC),
        datetime(2026, 10, 25, 1, 30, tzinfo=UTC),
        datetime(2026, 10, 25, 2, 0, tzinfo=UTC),
    ]
    [message] = [
        m for m in await _outbox(uow_factory) if m.payload.get("kind") == "escalate-to-lead"
    ]
    assert message.payload["enqueue_at"] == "2026-10-25T02:00:00Z"
