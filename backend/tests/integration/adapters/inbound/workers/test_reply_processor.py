"""The reply processor on real Neo4j (I08, DEC-165).

Friday 23 October 2026, London time (BST). UCR West has a figure of 3 from 08:15 and a capacity
prompt (C1) went to its reporter at 10:00, so its reply-by is 10:30. A reply of "4" at 10:12 is a
new figure. The phone hash is a synthetic 64-character hex string. No patient data: the texts are
numbers. Every Processed marker, report and Communication is read back from Neo4j.

The tenant is the one on the message, and it is bound before any unit of work opens: the use case
opens its own units, so the processor must not hold one around it.
"""

from datetime import UTC, datetime, time, timedelta
from typing import Any

import pytest
from neo4j import AsyncDriver

from diucs.adapters.inbound.workers.consumer import Outcome
from diucs.adapters.inbound.workers.outbox_relay import StaticTenants
from diucs.adapters.inbound.workers.reply_processor import reply_consumer, reply_key
from diucs.adapters.inbound.workers.servicebus_runner import ServiceBusRunner
from diucs.adapters.outbound.audit_neo4j.audit_log import ensure_audit_head
from diucs.adapters.outbound.graph_store.idempotency_store import DriverIdempotencyStore
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.application.ports.outbound.messaging import Communication
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenancy import current_scope_or_none
from diucs.application.use_cases.confirm_capacity import ConfirmCapacity
from diucs.application.use_cases.handle_inbound_text import (
    HandleInboundText,
    HandleInboundTextCommand,
)
from diucs.application.use_cases.report_capacity import ReportCapacity
from diucs.domain.codes import (
    Cadence,
    Channel,
    Measure,
    PractitionerRoleCode,
    ReportSource,
    ReportType,
    ServiceCategory,
)
from diucs.domain.errors import Conflict, ValidationFailed
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.people import Practitioner, PractitionerRole
from diucs.domain.model.service import AvailableTime, ServiceProfile
from tests.support.inbound_rig import (
    PHONE,
    RECEIVED_AT,
    Receiver,
    RecordingUseCase,
    UnitLog,
    logging_factory,
    raw,
    reply_message,
)
from tests.support.neo4j import count_nodes, read_tx

pytestmark = pytest.mark.asyncio(loop_scope="session")

SENT_KEY = "SM100"


def bst(hour: int, minute: int) -> datetime:
    return datetime(2026, 10, 23, hour, minute, tzinfo=UTC) - timedelta(hours=1)


@pytest.fixture
def uow_clock() -> FixedClock:
    return FixedClock(bst(10, 12))


@pytest.fixture
def tenants(tenant_id: str, other_tenant_id: str) -> StaticTenants:
    return StaticTenants([tenant_id, other_tenant_id])


async def _processed(driver: AsyncDriver) -> list[dict[str, Any]]:
    async def work(tx: Any) -> list[dict[str, Any]]:
        result = await tx.run(
            "MATCH (p:Processed) RETURN p.messageId AS messageId, p.consumer AS consumer, "
            "p.tenantId AS tenantId ORDER BY p.tenantId, p.messageId"
        )
        return [dict(record) async for record in result]

    return await read_tx(driver, work)


# --- 1. the command ------------------------------------------------------------------------------


async def test_a_reply_calls_the_use_case_once_with_the_phone_text_time_and_key(
    uow_factory: UnitOfWorkFactory, tenants: StaticTenants, tenant_id: str
) -> None:
    use_case = RecordingUseCase(uow_factory)
    consumer = reply_consumer(use_case, uow_factory, tenants)

    outcome = await consumer.handle(reply_message(tenant_id, "SM100", text="4"))

    assert outcome == Outcome("completed")
    assert use_case.commands == [
        HandleInboundTextCommand(
            idempotency_key=f"sms-reply:{tenant_id}:SM100",
            from_phone_hash=PHONE,
            text="4",
            received_at=RECEIVED_AT,
        )
    ]
    assert use_case.tenants == [tenant_id]
    assert current_scope_or_none() is not None  # the harness binding, restored after the message


async def test_the_use_case_opens_its_own_unit_so_no_unit_is_held_around_it(
    uow_factory: UnitOfWorkFactory, tenants: StaticTenants, tenant_id: str
) -> None:
    """The graph store refuses a second unit of work inside an open one (DEC-146 item 4). The
    stand-in opens one, as the real use case does, so this fails if the processor holds one."""
    use_case = RecordingUseCase(uow_factory)

    outcome = await reply_consumer(use_case, uow_factory, tenants).handle(reply_message(tenant_id))

    assert outcome.kind == "completed"


async def test_the_command_time_is_the_utc_instant_of_the_offset_it_carries(
    uow_factory: UnitOfWorkFactory, tenants: StaticTenants, tenant_id: str
) -> None:
    use_case = RecordingUseCase()
    local = datetime.fromisoformat("2026-10-23T10:12:00+01:00")

    await reply_consumer(use_case, uow_factory, tenants).handle(
        reply_message(tenant_id, received_at=local)
    )

    assert use_case.commands[0].received_at == bst(10, 12)
    assert use_case.commands[0].received_at.utcoffset() == timedelta(0)


# --- 2. a missing field --------------------------------------------------------------------------


@pytest.mark.parametrize("field", ["phone_hash", "text", "received_at", "provider_message_id"])
async def test_a_missing_field_is_dead_lettered_and_leaves_no_marker(
    uow_factory: UnitOfWorkFactory,
    tenants: StaticTenants,
    tenant_id: str,
    neo4j_driver: AsyncDriver,
    field: str,
) -> None:
    use_case = RecordingUseCase()

    outcome = await reply_consumer(use_case, uow_factory, tenants).handle(
        reply_message(tenant_id, omit=(field,))
    )

    assert outcome.kind == "dead-letter"
    assert use_case.commands == []
    assert await count_nodes(neo4j_driver, "Processed") == 0


# --- 3. the same message twice -------------------------------------------------------------------


async def test_the_same_message_twice_runs_the_use_case_once_and_leaves_one_marker(
    uow_factory: UnitOfWorkFactory,
    tenants: StaticTenants,
    tenant_id: str,
    neo4j_driver: AsyncDriver,
) -> None:
    use_case = RecordingUseCase(uow_factory)
    consumer = reply_consumer(use_case, uow_factory, tenants)

    first = await consumer.handle(reply_message(tenant_id))
    second = await consumer.handle(reply_message(tenant_id))

    assert (first.kind, second.kind) == ("completed", "duplicate")
    assert len(use_case.commands) == 1
    assert await _processed(neo4j_driver) == [
        {"messageId": "SM100", "consumer": "reply-processor", "tenantId": tenant_id}
    ]


# --- 4. the real use case ------------------------------------------------------------------------

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
ROLE_WEST = PractitionerRole(
    id="role-west",
    practitioner_id="prac-1",
    service_id="ucr-west",
    code=PractitionerRoleCode.DUTY_MANAGER,
    active=True,
    channel=Channel.TEXT,
    period_start=datetime(2026, 1, 1, tzinfo=UTC),
)


async def _seed_world(factory: UnitOfWorkFactory, driver: AsyncDriver) -> None:
    """A service, its reporter on PHONE, a figure of 3 from 08:15 and the 10:00 prompt."""
    await ensure_audit_head(driver)
    async with factory() as uow:
        await uow.services.save(UCR_WEST)
        await uow.people.save_practitioner(
            Practitioner(id="prac-1", active=True, display_name="Reporter One", phone_hash=PHONE)
        )
        await uow.people.save_role(ROLE_WEST)
        await uow.capacity.add(
            CapacityReport(
                id="seed-ucr-west",
                service_id="ucr-west",
                value=3,
                measure=Measure.REFERRALS_ACCEPTABLE,
                effective_at=bst(8, 15),
                source=ReportSource.TEXT,
                report_type=ReportType.NUMBER,
            )
        )
        await uow.communications.add(
            Communication(
                id="prompt-1",
                message_id="C1",
                channel=Channel.TEXT,
                recipient_role_id="role-west",
                about_id="ucr-west",
                payload_text="DIUCS: UCR West. We have 3 referrals in the next 2 hrs.",
                sent_at=bst(10, 0),
                delivery_status="sent",
            )
        )
        await uow.commit()


def _real_use_case(
    factory: UnitOfWorkFactory, driver: AsyncDriver, clock: FixedClock
) -> HandleInboundText:
    ids = SequentialIds("in")
    store = DriverIdempotencyStore(driver)
    return HandleInboundText(
        factory,
        clock,
        ids,
        store,
        InMemoryCache(clock),
        ReportCapacity(factory, clock, ids, store),
        ConfirmCapacity(factory, clock, ids, store),
    )


async def test_a_text_of_4_stores_a_capacity_observation_of_4_through_the_real_use_case(
    uow_factory: UnitOfWorkFactory,
    tenants: StaticTenants,
    tenant_id: str,
    neo4j_driver: AsyncDriver,
    uow_clock: FixedClock,
) -> None:
    await _seed_world(uow_factory, neo4j_driver)
    use_case = _real_use_case(uow_factory, neo4j_driver, uow_clock)
    consumer = reply_consumer(use_case, uow_factory, tenants)

    outcome = await consumer.handle(
        reply_message(tenant_id, "SM200", text="4", received_at=bst(10, 12))
    )

    assert outcome == Outcome("completed")
    async with uow_factory() as uow:
        latest = await uow.capacity.latest("ucr-west")
    assert latest is not None
    assert (latest.value, latest.source) == (4, ReportSource.TEXT)
    assert await count_nodes(neo4j_driver, "Observation") == 2  # the seeded 3 and the reply's 4
    assert [m["messageId"] for m in await _processed(neo4j_driver)] == ["SM200"]


async def test_a_redelivered_text_through_the_real_use_case_is_not_recorded_twice(
    uow_factory: UnitOfWorkFactory,
    tenants: StaticTenants,
    tenant_id: str,
    neo4j_driver: AsyncDriver,
    uow_clock: FixedClock,
) -> None:
    await _seed_world(uow_factory, neo4j_driver)
    consumer = reply_consumer(
        _real_use_case(uow_factory, neo4j_driver, uow_clock), uow_factory, tenants
    )
    message = reply_message(tenant_id, "SM200", text="4", received_at=bst(10, 12))

    await consumer.handle(message)
    second = await consumer.handle(message)

    assert second.kind == "duplicate"
    assert await count_nodes(neo4j_driver, "Observation") == 2


async def test_a_text_the_use_case_drops_is_still_completed(
    uow_factory: UnitOfWorkFactory,
    tenants: StaticTenants,
    tenant_id: str,
    neo4j_driver: AsyncDriver,
    uow_clock: FixedClock,
) -> None:
    """A phone that is nobody's reporter is dropped by the use case with no write; the message is
    finished, not retried."""
    await _seed_world(uow_factory, neo4j_driver)
    consumer = reply_consumer(
        _real_use_case(uow_factory, neo4j_driver, uow_clock), uow_factory, tenants
    )

    outcome = await consumer.handle(reply_message(tenant_id, "SM201", phone_hash="ee" * 32))

    assert outcome == Outcome("completed")
    assert await count_nodes(neo4j_driver, "Observation") == 1


# --- failures ------------------------------------------------------------------------------------


async def test_a_use_case_failure_is_a_retry_with_no_marker_and_the_next_delivery_runs_it_again(
    uow_factory: UnitOfWorkFactory,
    tenants: StaticTenants,
    tenant_id: str,
    neo4j_driver: AsyncDriver,
) -> None:
    use_case = RecordingUseCase(uow_factory)
    use_case.raises.append(RuntimeError("SECRET-STORE-TEXT"))
    consumer = reply_consumer(use_case, uow_factory, tenants)

    first = await consumer.handle(reply_message(tenant_id))
    assert first == Outcome("retry", "RuntimeError")
    assert await count_nodes(neo4j_driver, "Processed") == 0

    second = await consumer.handle(reply_message(tenant_id))

    assert second == Outcome("completed")
    assert len(use_case.commands) == 2
    assert use_case.commands[0].idempotency_key == use_case.commands[1].idempotency_key
    assert await count_nodes(neo4j_driver, "Processed") == 1


async def test_a_message_the_use_case_refuses_as_invalid_is_dead_lettered_without_its_text(
    uow_factory: UnitOfWorkFactory,
    tenants: StaticTenants,
    tenant_id: str,
    neo4j_driver: AsyncDriver,
) -> None:
    use_case = RecordingUseCase()
    use_case.raises.append(ValidationFailed("phone", "SECRET-REFUSAL-TEXT"))

    outcome = await reply_consumer(use_case, uow_factory, tenants).handle(
        reply_message(tenant_id, text="SECRET-REPLY-TEXT")
    )

    assert outcome.kind == "dead-letter"
    assert outcome.reason is not None
    assert "SECRET" not in outcome.reason
    assert PHONE not in outcome.reason
    assert await count_nodes(neo4j_driver, "Processed") == 0


async def test_a_conflict_from_the_use_case_is_a_retry_not_a_dead_letter(
    uow_factory: UnitOfWorkFactory, tenants: StaticTenants, tenant_id: str
) -> None:
    """A Conflict can be a race with another writer that the next delivery will not meet. The bus
    dead-letters the message after its delivery limit."""
    use_case = RecordingUseCase()
    use_case.raises.append(Conflict("another write got there first"))

    outcome = await reply_consumer(use_case, uow_factory, tenants).handle(reply_message(tenant_id))

    assert outcome == Outcome("retry", "Conflict")


async def test_a_store_that_fails_after_the_use_case_leaves_no_marker_and_the_replay_is_safe(
    uow_factory: UnitOfWorkFactory,
    tenants: StaticTenants,
    tenant_id: str,
    neo4j_driver: AsyncDriver,
) -> None:
    """The use case ran, then the marker could not be written. The next delivery runs the use case
    again with the same key (which it answers as a replay) and then marks."""
    log = UnitLog(fail_marks=1)
    factory = logging_factory(uow_factory, log)
    use_case = RecordingUseCase(factory)
    consumer = reply_consumer(use_case, factory, tenants)

    first = await consumer.handle(reply_message(tenant_id))
    assert first == Outcome("retry", "RuntimeError")
    assert await count_nodes(neo4j_driver, "Processed") == 0

    second = await consumer.handle(reply_message(tenant_id))

    assert second == Outcome("completed")
    assert [c.idempotency_key for c in use_case.commands] == [reply_key_for(tenant_id, "SM100")] * 2
    assert await count_nodes(neo4j_driver, "Processed") == 1


def reply_key_for(tenant: str, message_id: str) -> str:
    return f"sms-reply:{tenant}:{message_id}"


async def test_a_marker_that_another_delivery_wrote_first_is_a_duplicate(
    uow_factory: UnitOfWorkFactory, tenants: StaticTenants, tenant_id: str
) -> None:
    """Two deliveries of one message both pass the seen check; the second to mark finds the first's
    marker. The use case answered both (it is idempotent by key); the message is complete."""
    use_case = RecordingUseCase()

    async def mark_meanwhile() -> None:
        async with uow_factory() as uow:
            await uow.processed.mark_if_new("SM100", "reply-processor")
            await uow.commit()

    original = use_case.execute

    async def execute_then_lose_the_race(command: HandleInboundTextCommand) -> Any:
        result = await original(command)
        await mark_meanwhile()
        return result

    use_case.execute = execute_then_lose_the_race  # type: ignore[method-assign]

    outcome = await reply_consumer(use_case, uow_factory, tenants).handle(reply_message(tenant_id))

    assert outcome == Outcome("duplicate")


# --- the tenant ----------------------------------------------------------------------------------


@pytest.mark.parametrize("which", ["missing", "unknown", "network", "empty"])
async def test_a_message_with_no_known_tenant_is_dead_lettered_and_never_processed(
    uow_factory: UnitOfWorkFactory,
    tenants: StaticTenants,
    neo4j_driver: AsyncDriver,
    which: str,
) -> None:
    tenant = {"missing": None, "unknown": "tenant-zz", "network": "net-abcd1234", "empty": ""}
    message = reply_message(tenant[which])
    use_case = RecordingUseCase()
    log = UnitLog()

    consumer = reply_consumer(use_case, logging_factory(uow_factory, log), tenants)
    outcome = await consumer.handle(message)

    assert outcome.kind == "dead-letter"
    assert use_case.commands == []
    assert log.scopes == []  # no unit of work was opened, scoped or not
    assert await count_nodes(neo4j_driver, "Processed") == 0


async def test_a_suspended_tenant_is_dead_lettered(
    uow_factory: UnitOfWorkFactory, tenant_id: str, other_tenant_id: str
) -> None:
    """The directory lists the active tenants only; the one left out reads as unknown."""
    use_case = RecordingUseCase()
    only_b = StaticTenants([other_tenant_id])

    outcome = await reply_consumer(use_case, uow_factory, only_b).handle(reply_message(tenant_id))

    assert outcome.kind == "dead-letter"
    assert use_case.commands == []


async def test_two_tenants_with_the_same_sender_are_each_handled_in_their_own(
    uow_factory: UnitOfWorkFactory,
    tenants: StaticTenants,
    tenant_id: str,
    other_tenant_id: str,
    neo4j_driver: AsyncDriver,
) -> None:
    """Tenant A and tenant B each receive a text from the same phone hash. Each reaches the use case
    under its own tenant, with its own idempotency key, and the units of work around it open under
    that tenant. (The shared harness schema still holds the old single-property marker key, so the
    two provider ids differ here; the same id in both is in test_inbound_two_tenants.py.)"""
    use_case = RecordingUseCase(uow_factory)
    log = UnitLog()
    consumer = reply_consumer(use_case, logging_factory(uow_factory, log), tenants)

    a = await consumer.handle(reply_message(tenant_id, "SM100", text="4"))
    b = await consumer.handle(reply_message(other_tenant_id, "SM101", text="4"))

    assert (a.kind, b.kind) == ("completed", "completed")
    assert use_case.tenants == [tenant_id, other_tenant_id]
    assert [c.idempotency_key for c in use_case.commands] == [
        f"sms-reply:{tenant_id}:SM100",
        f"sms-reply:{other_tenant_id}:SM101",
    ]
    assert [c.from_phone_hash for c in use_case.commands] == [PHONE, PHONE]
    assert {scope.value for scope in log.scopes if scope is not None} == {
        tenant_id,
        other_tenant_id,
    }
    assert None not in log.scopes
    assert await _processed(neo4j_driver) == sorted(
        [
            {"messageId": "SM100", "consumer": "reply-processor", "tenantId": tenant_id},
            {"messageId": "SM101", "consumer": "reply-processor", "tenantId": other_tenant_id},
        ],
        key=lambda row: row["tenantId"],
    )

    again = await consumer.handle(reply_message(tenant_id, "SM100", text="4"))
    again_b = await consumer.handle(reply_message(other_tenant_id, "SM101", text="4"))
    assert (again.kind, again_b.kind) == ("duplicate", "duplicate")
    assert len(use_case.commands) == 2


async def test_the_idempotency_key_is_built_from_the_bound_tenant_in_one_place(
    tenant_id: str,
) -> None:
    assert reply_key("SM9") == f"sms-reply:{tenant_id}:SM9"


# --- the runner: one poison message does not block the queue --------------------------------------


async def test_a_poison_message_is_dead_lettered_and_the_next_one_is_processed(
    uow_factory: UnitOfWorkFactory,
    tenants: StaticTenants,
    tenant_id: str,
    neo4j_driver: AsyncDriver,
) -> None:
    use_case = RecordingUseCase(uow_factory)
    runner = ServiceBusRunner(
        client=None,  # type: ignore[arg-type]
        entity="inbound.replies",
        subscription=None,
        consumer=reply_consumer(use_case, uow_factory, tenants),
    )
    receiver = Receiver()

    await runner.process(receiver, raw(reply_message(tenant_id, "SM1", omit=("phone_hash",))))
    await runner.process(receiver, raw(reply_message(None, "SM2")))
    await runner.process(receiver, raw(reply_message("tenant-zz", "SM3")))
    await runner.process(receiver, raw(reply_message(tenant_id, "SM4")))

    assert receiver.calls == [
        ("dead-letter", "SM1"),
        ("dead-letter", "SM2"),
        ("dead-letter", "SM3"),
        ("complete", "SM4"),
    ]
    assert [c.idempotency_key for c in use_case.commands] == [f"sms-reply:{tenant_id}:SM4"]


async def test_the_tenant_property_of_a_received_message_is_the_one_bound(
    uow_factory: UnitOfWorkFactory,
    tenants: StaticTenants,
    other_tenant_id: str,
) -> None:
    use_case = RecordingUseCase()
    runner = ServiceBusRunner(
        client=None,  # type: ignore[arg-type]
        entity="inbound.replies",
        subscription=None,
        consumer=reply_consumer(use_case, uow_factory, tenants),
    )

    await runner.process(Receiver(), raw(reply_message(other_tenant_id, "SM5")))

    assert use_case.tenants == [other_tenant_id]
