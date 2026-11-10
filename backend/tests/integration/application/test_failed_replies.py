"""Integration tests for the replies the webhook could not take in (DEC-1359), on the real Neo4j.

The repository (one node per message id, idempotent add, newest first, closed once), the three use
cases (list with the sender's name, mark handled, process now through the queue) and the tenant
walls. Every value is invented; no phone number is stored, only a hash.
"""

from datetime import UTC, datetime, timedelta

import pytest
from neo4j import AsyncDriver

from overwatch.adapters.testing.fixed_clock import FixedClock
from overwatch.adapters.testing.memory_event_bus import ManualEventBus
from overwatch.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from overwatch.application.use_cases.failed_replies import (
    REPLIES_QUEUE,
    FailedReplyCommand,
    ListFailedReplies,
    MarkFailedReplyHandled,
    ReprocessFailedReply,
)
from overwatch.domain.errors import Conflict, NotAllowed, NotFound
from overwatch.domain.model.inbound_reply import (
    FailedStep,
    InboundReplyFailure,
    ReplyStatus,
    Resolution,
)
from overwatch.domain.model.people import Practitioner
from tests.support.booking_rig import ADVISOR, LEAD, at
from tests.support.neo4j import count_nodes
from tests.support.tenancy import as_tenant
from tests.support.uow import ensure_audit_heads

pytestmark = pytest.mark.asyncio(loop_scope="session")

SID_1 = "SM" + "1" * 32
SID_2 = "SM" + "2" * 32
HASH_KNOWN = "a" * 64
HASH_STRANGER = "b" * 64
FIRST = datetime(2026, 11, 10, 10, 1, 8, tzinfo=UTC)


def failure(
    sid: str = SID_1,
    *,
    when: datetime = FIRST,
    step: FailedStep = FailedStep.ENQUEUE,
    text: str = "Y",
    phone_hash: str = HASH_KNOWN,
) -> InboundReplyFailure:
    return InboundReplyFailure(
        sid=sid,
        received_at=when,
        step=step,
        error_type="ConnectionError",
        text=text,
        phone_hash=phone_hash,
    )


async def keep(uow_factory: UnitOfWorkFactory, *failures: InboundReplyFailure) -> list[bool]:
    made: list[bool] = []
    async with uow_factory() as uow:
        for item in failures:
            made.append(await uow.inbound_replies.add(item))
        await uow.commit()
    return made


def command(sid: str = SID_1, key: str = "k-1", actor=LEAD) -> FailedReplyCommand:  # type: ignore[no-untyped-def]
    return FailedReplyCommand(idempotency_key=key, actor=actor, sid=sid)


async def test_a_failure_is_kept_once_per_message_and_the_first_record_stands(
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    tenant_id: str,
    clean_graph: None,
) -> None:
    first = await keep(uow_factory, failure(text="Y"))
    second = await keep(uow_factory, failure(text="N", step=FailedStep.FIND_SENDER))

    assert first == [True] and second == [False]
    assert await count_nodes(neo4j_driver, "InboundReplyFailure") == 1
    async with uow_factory() as uow:
        stored = await uow.inbound_replies.get(SID_1)
    assert stored is not None
    assert (stored.text, stored.step, stored.status) == ("Y", FailedStep.ENQUEUE, ReplyStatus.OPEN)


async def test_the_open_list_is_newest_first_and_leaves_out_what_is_closed(
    uow_factory: UnitOfWorkFactory, tenant_id: str, clean_graph: None
) -> None:
    await keep(
        uow_factory, failure(SID_1, when=FIRST), failure(SID_2, when=FIRST + timedelta(hours=1))
    )

    async with uow_factory() as uow:
        assert [f.sid for f in await uow.inbound_replies.list_open()] == [SID_2, SID_1]
        closed = await uow.inbound_replies.mark_resolved(
            SID_2, resolution=Resolution.HANDLED, by="lead-1", at=FIRST
        )
        again = await uow.inbound_replies.mark_resolved(
            SID_2, resolution=Resolution.HANDLED, by="lead-1", at=FIRST
        )
        await uow.commit()
    async with uow_factory() as uow:
        assert [f.sid for f in await uow.inbound_replies.list_open()] == [SID_1]
        kept = await uow.inbound_replies.get(SID_2)
    assert closed is True and again is False
    assert (
        kept is not None and kept.resolution is Resolution.HANDLED and kept.resolved_by == "lead-1"
    )


async def test_the_lead_sees_who_sent_each_reply_when_the_hash_names_an_active_person(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str, clean_graph: None
) -> None:
    await ensure_audit_heads(neo4j_driver, tenant_id)
    async with uow_factory() as uow:
        await uow.people.save_practitioner(
            Practitioner(id="p-1", active=True, display_name="Dee Manager", phone_hash=HASH_KNOWN)
        )
        await uow.commit()
    await keep(
        uow_factory,
        failure(SID_1, when=FIRST),
        failure(SID_2, when=FIRST + timedelta(minutes=5), phone_hash=HASH_STRANGER, text="3"),
    )

    views = await ListFailedReplies(uow_factory).execute(LEAD)

    assert [(v.sid, v.sender_name, v.text) for v in views] == [
        (SID_2, None, "3"),
        (SID_1, "Dee Manager", "Y"),
    ]


async def test_only_the_lead_or_the_administrator_works_with_them(
    uow_factory: UnitOfWorkFactory, tenant_id: str, clean_graph: None
) -> None:
    clock = FixedClock(at(14, 20))
    with pytest.raises(NotAllowed):
        await ListFailedReplies(uow_factory).execute(ADVISOR)
    with pytest.raises(NotAllowed):
        await MarkFailedReplyHandled(uow_factory, clock).execute(command(actor=ADVISOR))


async def test_marking_handled_closes_it_audits_without_the_text_and_replays_on_the_same_key(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str, clean_graph: None
) -> None:
    await ensure_audit_heads(neo4j_driver, tenant_id)
    await keep(uow_factory, failure(text="a private word"))
    handler = MarkFailedReplyHandled(uow_factory, FixedClock(at(14, 20)))

    first = await handler.execute(command(key="k-1"))
    replay = await handler.execute(command(key="k-1"))

    assert first is Resolution.HANDLED and replay is Resolution.HANDLED
    async with uow_factory() as uow:
        assert await uow.inbound_replies.list_open() == []
    audit = await neo4j_driver.execute_query(
        "MATCH (a:AuditEvent {tenantId: $tenant}) WHERE a.useCase = 'MarkFailedReplyHandled' "
        "RETURN count(a) AS total, collect(properties(a)) AS shown",
        tenant=tenant_id,
    )
    assert audit.records[0]["total"] == 1
    assert "a private word" not in repr(audit.records[0]["shown"])
    with pytest.raises(Conflict):
        await handler.execute(command(key="k-2"))  # a second key finds it already dealt with


async def test_a_key_used_for_another_reply_is_refused_and_an_unknown_reply_is_not_found(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str, clean_graph: None
) -> None:
    await ensure_audit_heads(neo4j_driver, tenant_id)
    await keep(uow_factory, failure(SID_1), failure(SID_2))
    handler = MarkFailedReplyHandled(uow_factory, FixedClock(at(14, 20)))
    await handler.execute(command(SID_1, key="k-1"))

    with pytest.raises(Conflict):
        await handler.execute(command(SID_2, key="k-1"))
    with pytest.raises(NotFound):
        await handler.execute(command("SM" + "9" * 32, key="k-3"))


async def test_processing_it_now_queues_the_stored_reply_as_the_webhook_would_and_closes_it(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str, clean_graph: None
) -> None:
    await ensure_audit_heads(neo4j_driver, tenant_id)
    clock = FixedClock(at(14, 20))
    bus = ManualEventBus(clock)
    await keep(uow_factory, failure(text="Y"))

    result = await ReprocessFailedReply(uow_factory, clock, bus).execute(command())

    assert result is Resolution.REPROCESSED
    [message] = bus.enqueued_to(REPLIES_QUEUE)
    assert message.id == SID_1 and message.event_type == "SmsReceived"
    assert message.tenant_id == tenant_id
    assert message.payload == {
        "phone_hash": HASH_KNOWN,
        "text": "Y",
        "received_at": FIRST.isoformat(),
        "provider_message_id": SID_1,
    }
    async with uow_factory() as uow:
        stored = await uow.inbound_replies.get(SID_1)
    assert stored is not None and stored.resolution is Resolution.REPROCESSED


async def test_a_queue_that_fails_leaves_the_reply_open_for_another_try(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str, clean_graph: None
) -> None:
    await ensure_audit_heads(neo4j_driver, tenant_id)
    clock = FixedClock(at(14, 20))

    class Down(ManualEventBus):
        async def enqueue(self, queue: str, message: object) -> None:  # type: ignore[override]
            raise ConnectionError("the queue is down")

    await keep(uow_factory, failure())
    with pytest.raises(ConnectionError):
        await ReprocessFailedReply(uow_factory, clock, Down(clock)).execute(command())

    async with uow_factory() as uow:
        assert [f.sid for f in await uow.inbound_replies.list_open()] == [SID_1]
    well = ManualEventBus(clock)
    await ReprocessFailedReply(uow_factory, clock, well).execute(command(key="k-2"))
    assert len(well.enqueued_to(REPLIES_QUEUE)) == 1


async def test_another_tenant_sees_and_changes_none_of_it(
    uow_factory: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    tenant_id: str,
    other_tenant_id: str,
    clean_graph: None,
) -> None:
    import dataclasses

    await ensure_audit_heads(neo4j_driver, tenant_id, other_tenant_id)
    await keep(uow_factory, failure())
    lead_b = dataclasses.replace(LEAD, tenant_id=other_tenant_id)

    with as_tenant(other_tenant_id):
        assert await ListFailedReplies(uow_factory_b).execute(lead_b) == []
        with pytest.raises(NotFound):
            await MarkFailedReplyHandled(uow_factory_b, FixedClock(at(14, 20))).execute(
                command(actor=lead_b)
            )
        # B can keep the same message id for itself without touching A's record.
        assert await keep(uow_factory_b, failure(text="other")) == [True]

    async with uow_factory() as uow:
        mine = await uow.inbound_replies.get(SID_1)
    assert mine is not None and mine.text == "Y" and mine.status is ReplyStatus.OPEN
