"""Integration tests for ReportCapacity (U01), against the real Neo4j the harness starts.

Seeds go through committed units of work; every assertion reads back through a fresh unit of
work or the harness helpers, so it checks what was really stored (DEC-004). Values are synthetic
sample values from the prompt. There is no patient data.

Clock: Friday 23 October 2026 at 13:12 UTC (14:12 BST). The next due after that is 16:00 BST
(DEC-100 item 1).
"""

import dataclasses
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, time, timedelta
from typing import Any

import pytest
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.idempotency_store import DriverIdempotencyStore
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.application.actor import Actor
from diucs.application.ports.outbound.outbox import OutboxMessage
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases import report_capacity
from diucs.application.use_cases.report_capacity import (
    ReportCapacity,
    ReportCapacityCommand,
    ReportCapacityResult,
)
from diucs.domain.codes import (
    Cadence,
    Channel,
    Measure,
    ReportFlagReason,
    ReportSource,
    ReportType,
    Role,
    ServiceCategory,
    Status,
)
from diucs.domain.errors import Conflict, DomainError, NotAllowed, NotFound, ValidationFailed
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.flags import SERVICE_FLAG_SUSPENDED, ServiceFlag
from diucs.domain.model.service import AvailableTime, ServiceProfile
from tests.support.neo4j import count_nodes, read_tx

Seed = Callable[..., Awaitable[None]]

pytestmark = pytest.mark.asyncio(loop_scope="session")

NOW = datetime(2026, 10, 23, 13, 12, tzinfo=UTC)  # 14:12 BST, Friday
NEXT_DUE_LONDON = "16:00"  # the first due after NOW (DEC-100 item 1). The prompt's 14:00 is
# before NOW, so it cannot be the next prompt; the expectation is 16:00 (DEC-101).

REPORTER = Actor(
    role=Role.REPORTER,
    practitioner_id="prac-reporter-1",
    device_id="device-1",
    channel="text",
    service_ids=frozenset({"ucr-west"}),
)
LINK_REPORTER = dataclasses.replace(REPORTER, channel="link")
ADVISOR = Actor(
    role=Role.ADVISOR,
    practitioner_id="prac-advisor-1",
    device_id=None,
    channel="web",
    service_ids=frozenset(),
)
LEAD = dataclasses.replace(ADVISOR, role=Role.LEAD, practitioner_id="prac-lead-1")

UCR_WEST = ServiceProfile(
    id="ucr-west",
    name="UCR West",
    category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
    measure=Measure.REFERRALS_ACCEPTABLE,
    unit_label="referrals",
    established_capacity=8,
    can_exceed_established=False,
    usual_range=(0, 8),
    cadence=Cadence.EVERY_2_HRS,
    available_times=(AvailableTime.every_day(time(8, 0), time(20, 0)),),
    channel=Channel.TEXT,
    limited_level_percent=80,
)


def _rig(factory: UnitOfWorkFactory, driver: AsyncDriver) -> tuple[ReportCapacity, FixedClock]:
    """A use case and its clock. Tests move the clock with set() between calls; the ids are
    shared by the use case, so a second call never reuses a report id."""
    clock = FixedClock(NOW)
    use_case = ReportCapacity(factory, clock, SequentialIds(), DriverIdempotencyStore(driver))
    return use_case, clock


def _command(
    value: int,
    *,
    key: str = "key-1",
    actor: Actor = REPORTER,
    service_id: str = "ucr-west",
    source: ReportSource = ReportSource.TEXT,
    effective_at: datetime | None = None,
    performer_role_id: str | None = None,
    replaced_value: int | None = None,
    flag: ReportFlagReason | None = None,
) -> ReportCapacityCommand:
    return ReportCapacityCommand(
        idempotency_key=key,
        actor=actor,
        service_id=service_id,
        value=value,
        source=source,
        effective_at=effective_at,
        performer_role_id=performer_role_id,
        replaced_value=replaced_value,
        flag=flag,
    )


async def _outbox(factory: UnitOfWorkFactory) -> list[OutboxMessage]:
    async with factory() as uow:
        return await uow.outbox.pending(limit=1000)


async def _events(factory: UnitOfWorkFactory, event_type: str) -> list[OutboxMessage]:
    return [m for m in await _outbox(factory) if m.event_type == event_type]


async def _communications(driver: AsyncDriver) -> list[dict[str, Any]]:
    async def work(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        result = await tx.run(
            "MATCH (c:Communication) OPTIONAL MATCH (c)-[:TOPIC]->(t:Concept) "
            "RETURN c.payloadText AS text, c.deliveryStatus AS status, t.code AS messageId"
        )
        return await result.data()

    return await read_tx(driver, work)


async def _latest(factory: UnitOfWorkFactory, service_id: str) -> CapacityReport | None:
    async with factory() as uow:
        return await uow.capacity.latest(service_id)


async def test_text_report_is_stored_and_emits_both_events(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)

    result = await _rig(uow_factory, neo4j_driver)[0].execute(_command(4))

    latest = await _latest(uow_factory, "ucr-west")
    assert latest is not None
    assert latest.value == 4
    assert isinstance(latest.value, int)
    assert latest.report_type is ReportType.NUMBER
    assert latest.effective_at == NOW
    assert latest.effective_at.utcoffset() == timedelta(0)
    assert result == ReportCapacityResult(
        report_id=latest.id,
        status=Status.ACCEPTING,
        status_changed=True,
        next_due=datetime(2026, 10, 23, 15, 0, tzinfo=UTC),
    )
    reported = await _events(uow_factory, "CapacityReported")
    changed = await _events(uow_factory, "StatusChanged")
    assert len(reported) == 1
    assert len(changed) == 1
    for message in (*reported, *changed):
        assert message.topic == "capacity.events"
        assert message.session_id == "ucr-west"


async def test_a_performer_gets_the_c3_echo(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)

    await _rig(uow_factory, neo4j_driver)[0].execute(_command(4, performer_role_id="role-1"))

    rows = await _communications(neo4j_driver)
    assert len(rows) == 1
    assert rows[0]["messageId"] == "C3"
    assert rows[0]["status"] == "queued"
    assert "UCR West: 4 referrals" in rows[0]["text"]
    assert f"Next prompt {NEXT_DUE_LONDON}." in rows[0]["text"]
    sends = await _events(uow_factory, "SendMessage")
    assert len(sends) == 1
    assert sends[0].payload["recipient_role_id"] == "role-1"
    assert "UCR West: 4 referrals" in sends[0].payload["text"]
    assert f"Next prompt {NEXT_DUE_LONDON}." in sends[0].payload["text"]
    assert set(sends[0].payload) == {
        "communication_id",
        "message_id",
        "channel",
        "recipient_role_id",
        "text",
    }
    assert sends[0].payload["message_id"] == "C3"
    assert sends[0].payload["channel"] == "text"


async def test_a_limited_threshold_crossing_emits_status_changed(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)
    use_case, clock = _rig(uow_factory, neo4j_driver)
    await use_case.execute(_command(4, key="key-4"))

    clock.set(NOW + timedelta(minutes=1))
    one = await use_case.execute(_command(1, key="key-1"))

    assert one.status is Status.LIMITED
    assert one.status_changed is True
    changes = await _events(uow_factory, "StatusChanged")
    assert len(changes) == 2
    assert changes[-1].payload["before"] == "accepting"
    assert changes[-1].payload["after"] == "limited"


async def test_a_report_that_keeps_the_status_emits_no_status_changed(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)
    use_case, clock = _rig(uow_factory, neo4j_driver)
    await use_case.execute(_command(4, key="key-4"))
    changes_before = len(await _events(uow_factory, "StatusChanged"))

    clock.set(NOW + timedelta(minutes=1))
    three = await use_case.execute(_command(3, key="key-3"))

    assert three.status is Status.ACCEPTING
    assert three.status_changed is False
    assert len(await _events(uow_factory, "StatusChanged")) == changes_before


async def test_the_echo_can_be_switched_off_for_a_caller_that_sends_its_own_reply(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    """U05 answers a grouped reply with one C10 and so asks for no per-service C3 (DEC-148). The
    performer is still recorded on the report."""
    await seed_service(UCR_WEST)

    await _rig(uow_factory, neo4j_driver)[0].execute(
        dataclasses.replace(_command(4, performer_role_id="role-1"), send_echo=False)
    )

    assert await _communications(neo4j_driver) == []
    assert await _events(uow_factory, "SendMessage") == []
    latest = await _latest(uow_factory, "ucr-west")
    assert latest is not None
    assert latest.performer_role_id == "role-1"


async def test_a_key_reused_with_the_echo_switched_is_a_different_report(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)
    use_case = _rig(uow_factory, neo4j_driver)[0]
    await use_case.execute(_command(4, performer_role_id="role-1"))

    with pytest.raises(Conflict):
        await use_case.execute(
            dataclasses.replace(_command(4, performer_role_id="role-1"), send_echo=False)
        )


async def test_a_replaced_figure_is_echoed_as_c4_and_a_link_is_not_echoed(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)
    use_case, clock = _rig(uow_factory, neo4j_driver)
    await use_case.execute(_command(4, key="key-4"))

    clock.set(NOW + timedelta(minutes=1))
    await use_case.execute(_command(1, key="key-1", performer_role_id="role-1", replaced_value=4))
    rows = await _communications(neo4j_driver)
    assert [row["messageId"] for row in rows] == ["C4"]
    assert "Replaces 4" in rows[0]["text"]

    clock.set(NOW + timedelta(minutes=2))
    await use_case.execute(
        _command(
            2,
            key="key-2",
            source=ReportSource.LINK,
            actor=LINK_REPORTER,
            performer_role_id="role-1",
        )
    )
    assert len(await _communications(neo4j_driver)) == 1
    assert len(await _events(uow_factory, "SendMessage")) == 1


@pytest.mark.parametrize("value", [-1, 1000])
async def test_a_value_outside_zero_to_999_is_refused_and_writes_nothing(
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    seed_service: Seed,
    value: int,
) -> None:
    await seed_service(UCR_WEST)

    with pytest.raises(ValidationFailed) as refused:
        await _rig(uow_factory, neo4j_driver)[0].execute(
            _command(value, performer_role_id="role-1")
        )

    assert refused.value.field == "value"
    assert await count_nodes(neo4j_driver, "Observation") == 0
    assert await count_nodes(neo4j_driver, "OutboxMessage") == 0
    assert await count_nodes(neo4j_driver, "AuditEvent") == 0


async def test_a_report_from_the_future_is_refused(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)

    with pytest.raises(ValidationFailed) as refused:
        await _rig(uow_factory, neo4j_driver)[0].execute(
            _command(4, effective_at=NOW + timedelta(minutes=1))
        )

    assert refused.value.field == "effective_at"
    assert await count_nodes(neo4j_driver, "Observation") == 0


async def test_a_report_flag_is_refused_until_u07_records_flags(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)

    with pytest.raises(ValidationFailed) as refused:
        await _rig(uow_factory, neo4j_driver)[0].execute(
            _command(4, flag=ReportFlagReason.MANY_CHANGES)
        )

    assert refused.value.field == "flag"
    assert await count_nodes(neo4j_driver, "Observation") == 0


async def test_a_reporter_without_the_service_is_refused(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)
    other_reporter = dataclasses.replace(REPORTER, service_ids=frozenset({"ucr-east"}))

    with pytest.raises(NotAllowed):
        await _rig(uow_factory, neo4j_driver)[0].execute(_command(4, actor=other_reporter))

    assert await count_nodes(neo4j_driver, "Observation") == 0
    assert await count_nodes(neo4j_driver, "OutboxMessage") == 0
    assert await count_nodes(neo4j_driver, "AuditEvent") == 0


async def test_an_unknown_service_is_not_found(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)

    with pytest.raises(NotFound):
        await _rig(uow_factory, neo4j_driver)[0].execute(
            _command(4, service_id="ucr-nowhere", actor=LEAD, source=ReportSource.ADVISOR_PHONED)
        )

    assert await count_nodes(neo4j_driver, "Observation") == 0


async def test_an_inactive_service_is_not_found(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(dataclasses.replace(UCR_WEST, active=False))

    with pytest.raises(NotFound):
        await _rig(uow_factory, neo4j_driver)[0].execute(_command(4))

    assert await count_nodes(neo4j_driver, "Observation") == 0
    assert await count_nodes(neo4j_driver, "OutboxMessage") == 0


async def test_an_advisor_may_report_a_phoned_figure_for_any_service(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)

    result = await _rig(uow_factory, neo4j_driver)[0].execute(
        _command(5, actor=ADVISOR, source=ReportSource.ADVISOR_PHONED)
    )

    assert result.status is Status.ACCEPTING
    latest = await _latest(uow_factory, "ucr-west")
    assert latest is not None
    assert latest.source is ReportSource.ADVISOR_PHONED


@pytest.mark.parametrize(
    ("actor", "source"),
    [
        (ADVISOR, ReportSource.TEXT),
        (REPORTER, ReportSource.ADVISOR_PHONED),
    ],
)
async def test_only_an_advisor_or_lead_may_name_the_phoned_source(
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    seed_service: Seed,
    actor: Actor,
    source: ReportSource,
) -> None:
    await seed_service(UCR_WEST)

    with pytest.raises(NotAllowed):
        await _rig(uow_factory, neo4j_driver)[0].execute(_command(4, actor=actor, source=source))

    assert await count_nodes(neo4j_driver, "Observation") == 0


async def test_a_report_to_a_suspended_service_emits_no_status_change(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    suspended = ServiceFlag(
        service_id="ucr-west",
        code=SERVICE_FLAG_SUSPENDED,
        active=True,
        reason="sample reason",
        actor_id="prac-lead-1",
        at=NOW - timedelta(hours=1),
    )
    await seed_service(UCR_WEST, flags=(suspended,))

    result = await _rig(uow_factory, neo4j_driver)[0].execute(_command(4))

    assert result.status is Status.NOT_UPDATED
    assert result.status_changed is False
    assert await _events(uow_factory, "StatusChanged") == []
    assert len(await _events(uow_factory, "CapacityReported")) == 1


async def test_the_same_key_twice_replays_the_first_result(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)
    use_case, _ = _rig(uow_factory, neo4j_driver)

    first = await use_case.execute(_command(4, key="same-key"))
    outbox_after_first = len(await _outbox(uow_factory))
    second = await use_case.execute(_command(4, key="same-key"))

    assert second.replayed is True
    assert first.replayed is False
    assert second.report_id == first.report_id
    assert await count_nodes(neo4j_driver, "Observation") == 1
    assert await count_nodes(neo4j_driver, "AuditEvent") == 1
    assert len(await _outbox(uow_factory)) == outbox_after_first


async def test_the_audit_record_has_the_report_shape_and_the_chain_verifies(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)
    result = await _rig(uow_factory, neo4j_driver)[0].execute(_command(4))

    async with uow_factory() as uow:
        records = await uow.audit.records()
        chain_ok = await uow.audit.verify_chain()

    assert len(records) == 1
    entry = records[0].entry
    assert entry.action == "C"
    assert entry.use_case == "ReportCapacity"
    assert entry.actor == REPORTER
    assert entry.entity_ids == (result.report_id, "ucr-west")
    assert entry.at == NOW
    assert entry.snapshot is not None
    assert entry.snapshot["value"] == 4
    assert entry.snapshot["source"] == "text"
    assert entry.snapshot["status_before"] == "not-updated"
    assert entry.snapshot["status_after"] == "accepting"
    assert chain_ok is True


async def test_a_naive_effective_time_is_refused(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)

    with pytest.raises(ValidationFailed) as refused:
        await _rig(uow_factory, neo4j_driver)[0].execute(
            _command(4, effective_at=datetime(2026, 10, 23, 13, 0))
        )

    assert refused.value.field == "effective_at"
    assert await count_nodes(neo4j_driver, "Observation") == 0


async def test_a_back_dated_report_does_not_replace_the_latest_figure(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)
    use_case, clock = _rig(uow_factory, neo4j_driver)
    await use_case.execute(_command(4, key="key-4"))

    clock.set(NOW + timedelta(minutes=1))
    back_dated = await use_case.execute(
        _command(3, key="key-3", effective_at=NOW - timedelta(minutes=10))
    )

    assert back_dated.status is Status.ACCEPTING
    assert back_dated.status_changed is False
    latest = await _latest(uow_factory, "ucr-west")
    assert latest is not None
    assert latest.value == 4
    assert latest.effective_at == NOW
    assert len(await _events(uow_factory, "CapacityReported")) == 2


@pytest.mark.parametrize(
    ("actor", "source"),
    [
        (LEAD, ReportSource.TEXT),
        (dataclasses.replace(ADVISOR, role=Role.CLINICAL), ReportSource.ADVISOR_PHONED),
    ],
)
async def test_a_role_that_may_not_report_is_refused(
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    seed_service: Seed,
    actor: Actor,
    source: ReportSource,
) -> None:
    await seed_service(UCR_WEST)

    with pytest.raises(NotAllowed):
        await _rig(uow_factory, neo4j_driver)[0].execute(_command(4, actor=actor, source=source))

    assert await count_nodes(neo4j_driver, "Observation") == 0


@pytest.mark.parametrize("value", [0, 999])
async def test_a_value_at_the_bounds_is_accepted(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed, value: int
) -> None:
    await seed_service(UCR_WEST)

    result = await _rig(uow_factory, neo4j_driver)[0].execute(_command(value))

    latest = await _latest(uow_factory, "ucr-west")
    assert latest is not None
    assert latest.value == value
    assert result.report_id == latest.id


async def test_a_reused_key_with_a_different_body_is_refused(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)
    use_case = _rig(uow_factory, neo4j_driver)[0]
    await use_case.execute(_command(4, key="same-key"))

    with pytest.raises(Conflict):
        await use_case.execute(_command(3, key="same-key"))

    assert await count_nodes(neo4j_driver, "Observation") == 1
    assert await count_nodes(neo4j_driver, "AuditEvent") == 1


class _MissingEarlyRead:
    """An idempotency store whose early read always misses, as if another request had stored the
    key after the early read and before the unit of work (DEC-106 item 2). Writes go through."""

    def __init__(self, inner: DriverIdempotencyStore) -> None:
        self._inner = inner

    async def get(self, key: str) -> object | None:
        return None

    async def put(self, key: str, result: object) -> None:
        await self._inner.put(key, result)


async def test_a_replay_is_decided_inside_the_unit_of_work(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)
    first = await _rig(uow_factory, neo4j_driver)[0].execute(_command(4, key="race-key"))
    racing = ReportCapacity(
        uow_factory,
        FixedClock(NOW),
        SequentialIds(),
        _MissingEarlyRead(DriverIdempotencyStore(neo4j_driver)),
    )

    second = await racing.execute(_command(4, key="race-key"))

    assert second.replayed is True
    assert second.report_id == first.report_id
    assert await count_nodes(neo4j_driver, "Observation") == 1
    assert await count_nodes(neo4j_driver, "AuditEvent") == 1


async def test_a_reused_key_from_a_different_practitioner_is_refused_before_any_check(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)
    use_case = _rig(uow_factory, neo4j_driver)[0]
    await use_case.execute(_command(4, key="shared-key"))
    other_reporter = dataclasses.replace(REPORTER, practitioner_id="prac-reporter-2")

    with pytest.raises(Conflict):
        await use_case.execute(_command(4, key="shared-key", actor=other_reporter))

    assert await count_nodes(neo4j_driver, "Observation") == 1


@pytest.mark.parametrize("replaced", [-1, 1000])
async def test_a_replaced_value_outside_zero_to_999_is_refused_and_writes_nothing(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed, replaced: int
) -> None:
    await seed_service(UCR_WEST)

    with pytest.raises(ValidationFailed) as refused:
        await _rig(uow_factory, neo4j_driver)[0].execute(_command(4, replaced_value=replaced))

    assert refused.value.field == "replaced_value"
    assert await count_nodes(neo4j_driver, "Observation") == 0
    assert await count_nodes(neo4j_driver, "AuditEvent") == 0


async def test_an_echo_with_no_next_prompt_is_refused_and_writes_nothing(
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    seed_service: Seed,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No valid profile reaches this state (see test_next_due_total.py). The state is built by
    # replacing next_due, so the guard in execute is exercised and nothing is written.
    await seed_service(UCR_WEST)
    monkeypatch.setattr(report_capacity, "next_due", lambda profile, now: None)

    with pytest.raises(DomainError, match="next due instant"):
        await _rig(uow_factory, neo4j_driver)[0].execute(_command(4, performer_role_id="role-1"))

    assert await count_nodes(neo4j_driver, "Observation") == 0
    assert await count_nodes(neo4j_driver, "AuditEvent") == 0
    assert await count_nodes(neo4j_driver, "OutboxMessage") == 0
