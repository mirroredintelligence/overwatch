"""Integration tests for MissedReportLadder and the stop in record_report (U06), on the real Neo4j.

The service is "Virtual ward · frailty" (reports every 2 hours, 08:00 to 20:00). Its 12:00 prompt
is sent by SendPrompts (U03) and nobody replies; the clock is then moved to each step of the ladder:
reminder 12:30, phone task 13:00, escalation 13:30 (London, Friday 23 October 2026, BST). Synthetic
values only: no patient data, no real phone number.
"""

import asyncio
import dataclasses
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, time, timedelta
from typing import Any, Self

import pytest
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.idempotency_store import DriverIdempotencyStore
from diucs.adapters.outbound.graph_store.link_token_repository import Neo4jLinkTokenRepository
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.application.actor import Actor
from diucs.application.ports.outbound.messaging import Communication
from diucs.application.ports.outbound.outbox import OutboxMessage
from diucs.application.ports.outbound.tokens import LinkTokenService
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.scheduling import schedule_work
from diucs.application.use_cases.confirm_capacity import ConfirmCapacity, ConfirmCapacityCommand
from diucs.application.use_cases.missed_report_ladder import (
    ESCALATED,
    IGNORED,
    PHONE_TASK_RAISED,
    REMINDED,
    STOPPED,
    LadderStepCommand,
)
from diucs.application.work import CANCELLED, DONE, SCHEDULED, WorkKind
from diucs.domain.codes import Channel, ReportSource, Role
from diucs.domain.errors import Conflict, NotFound, ValidationFailed
from diucs.domain.messages.privacy_guard import find_patient_data
from diucs.domain.model.flags import SERVICE_FLAG_SUSPENDED, ServiceFlag
from diucs.domain.model.service import AvailableTime
from tests.support.actors import ACTOR_TENANT
from tests.support.ladder_rig import (
    LINK_BASE,
    PHONE_HASH_1,
    PHONE_HASH_2,
    SECRET,
    SYSTEM_ACTOR,
    Rig,
    build_rig,
    london,
    reporter,
    seed_people,
    seed_report,
    virtual_ward,
)
from tests.support.neo4j import count_nodes, read_tx, run_nodes

Seed = Callable[..., Awaitable[None]]

pytestmark = pytest.mark.asyncio(loop_scope="session")

SERVICE = "vw-frailty"
FIGURE_AT = london(10, 5)
COUNTED_LABELS = ("Communication", "LinkToken", "ScheduledWork", "OutboxMessage", "AuditEvent")
LINK_AT_END = re.compile(rf"{re.escape(LINK_BASE)}/(\S+) By ")


@pytest.fixture
def rig(uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str) -> Rig:
    return build_rig(uow_factory, neo4j_driver, tenant_id)


async def _prompted(
    rig: Rig,
    seed_service: Seed,
    *,
    reporters: int = 1,
    figure_at: datetime | None = FIGURE_AT,
) -> tuple[str, ...]:
    """The service, its reporters and a 12:00 prompt that nobody answers. Returns the ids of the
    prompt communications, one for each reporter (the ladder of each is about its communication)."""
    await seed_service(virtual_ward())
    phones = (PHONE_HASH_1, PHONE_HASH_2)
    await seed_people(rig.factory, *(reporter(n, phones[n - 1]) for n in range(1, reporters + 1)))
    if figure_at is not None:
        await seed_report(rig.factory, figure_at)
    result = await rig.prompt(london(12, 0))
    assert result.sent is True
    assert len(result.communication_ids) == reporters
    return result.communication_ids


async def _counts(driver: AsyncDriver) -> dict[str, int]:
    return {label: await count_nodes(driver, label) for label in COUNTED_LABELS}


async def _communications(driver: AsyncDriver) -> list[dict[str, Any]]:
    async def work(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        result = await tx.run(
            "MATCH (c:Communication {tenantId: $tenant}) OPTIONAL MATCH (c {tenantId: "
            "$tenant})-[:TOPIC]->(t:Concept {tenantId: $tenant}) "
            "OPTIONAL MATCH (c {tenantId: $tenant})-[:RECIPIENT]->(r:PractitionerRole {tenantId: "
            "$tenant}) "
            "OPTIONAL MATCH (c {tenantId: $tenant})-[:ABOUT]->(s:HealthcareService {tenantId: "
            "$tenant}) "
            "RETURN c.id AS id, c.payloadText AS text, c.deliveryStatus AS status, "
            "t.code AS messageId, r.id AS role, s.id AS service ORDER BY c.id"
        )
        return await result.data()

    return await read_tx(driver, work)


async def _reminders(driver: AsyncDriver) -> list[dict[str, Any]]:
    return [row for row in await _communications(driver) if row["messageId"] == "C8"]


async def _every_node_property(driver: AsyncDriver) -> list[dict[str, Any]]:
    async def work(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        result = await run_nodes(tx, "properties(n) AS props")
        return await result.data()

    return [row["props"] for row in await read_tx(driver, work)]


async def _resolve(driver: AsyncDriver, token: str) -> Any:
    async def work(tx: AsyncManagedTransaction) -> Any:
        service = LinkTokenService(
            Neo4jLinkTokenRepository(tx),
            FixedSecretStore({"link-token": SECRET}),
            FixedClock(london(12, 30)),
        )
        return await service.resolve(token)

    return await read_tx(driver, work)


def _statuses(works: list[Any]) -> list[str]:
    return [work.status for work in works]


async def _ladder_statuses(rig: Rig, about_id: str) -> dict[WorkKind, str]:
    return {
        kind: (await rig.work(about_id, kind)).status
        for kind in (WorkKind.REMINDER, WorkKind.PHONE_TASK, WorkKind.ESCALATE_TO_LEAD)
    }


def _of_type(messages: list[OutboxMessage], message_id: str) -> list[OutboxMessage]:
    return [m for m in messages if m.payload.get("message_id") == message_id]


# --- 1 The reminder at +30 -----------------------------------------------------------------------


async def test_the_reminder_sends_c8_with_a_fresh_link_and_the_board_reads_not_updated(
    rig: Rig, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    [prompt] = await _prompted(rig, seed_service)

    result = await rig.step(prompt, WorkKind.REMINDER, london(12, 30))

    assert result.action == REMINDED
    assert result.replayed is False
    [reminder] = await _reminders(neo4j_driver)
    assert result.communication_id == reminder["id"]
    assert reminder["status"] == "queued"
    assert reminder["role"] == "role-1"
    assert reminder["service"] == SERVICE
    # The record holds the words with the link replaced: the token is never stored.
    assert reminder["text"] == (
        "DIUCS reminder: Virtual ward · frailty has not updated. Confirm or update: [link] "
        "By 13:00."
    )
    [message] = _of_type(await rig.events("SendMessage"), "C8")
    sent = rig.opened(message)
    assert message.payload["communication_id"] == reminder["id"]
    assert message.payload["recipient_role_id"] == "role-1"
    assert message.topic == "messages.outbound"
    match = LINK_AT_END.search(sent["text"])
    assert match is not None
    token = match.group(1)
    assert find_patient_data(sent["text"]) == []
    # A fresh link: tied to this reminder and this phone, and it expires at the new reply-by.
    record = await _resolve(neo4j_driver, token)
    assert record is not None
    assert record.about_id == reminder["id"]
    assert record.phone_hash == PHONE_HASH_1
    assert record.expires_at == london(13, 0)
    assert record.used_at is None
    assert not any(
        token in str(value)
        for props in await _every_node_property(neo4j_driver)
        for value in props.values()
    )


async def test_the_reminder_moves_the_status_to_not_updated_and_the_step_is_done(
    rig: Rig, seed_service: Seed
) -> None:
    [prompt] = await _prompted(rig, seed_service)

    await rig.step(prompt, WorkKind.REMINDER, london(12, 30))

    [changed] = await rig.events("StatusChanged")
    assert changed.topic == "capacity.events"
    assert changed.session_id == SERVICE
    assert changed.payload == {
        "service_id": SERVICE,
        "before": "accepting",
        "after": "not-updated",
        "at": "2026-10-23T11:30:00Z",
    }
    assert await _ladder_statuses(rig, prompt) == {
        WorkKind.REMINDER: DONE,
        WorkKind.PHONE_TASK: SCHEDULED,
        WorkKind.ESCALATE_TO_LEAD: SCHEDULED,
    }


async def test_the_reminder_is_audited_without_the_link(rig: Rig, seed_service: Seed) -> None:
    [prompt] = await _prompted(rig, seed_service)
    work = await rig.work(prompt, WorkKind.REMINDER)

    result = await rig.run(work, london(12, 30))

    async with rig.factory() as uow:
        records = await uow.audit.records()
    entry = records[-1].entry
    assert entry.use_case == "MissedReportLadder"
    assert entry.entity_ids == (work.id, result.communication_id, SERVICE)
    assert entry.snapshot == {
        "kind": "reminder",
        "action": "reminded",
        "due_at": "2026-10-23T11:00:00Z",
    }
    assert entry.at == london(12, 30)
    assert entry.actor == SYSTEM_ACTOR


async def test_a_late_step_gives_a_full_new_reply_window_from_when_it_runs(
    rig: Rig, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    [prompt] = await _prompted(rig, seed_service)

    await rig.step(prompt, WorkKind.REMINDER, london(12, 45))

    [reminder] = await _reminders(neo4j_driver)
    assert reminder["text"].endswith("By 13:15.")
    [message] = _of_type(await rig.events("SendMessage"), "C8")
    match = LINK_AT_END.search(rig.opened(message)["text"])
    assert match is not None
    record = await _resolve(neo4j_driver, match.group(1))
    assert record.expires_at == london(13, 15)
    [changed] = await rig.events("StatusChanged")
    assert changed.payload["at"] == "2026-10-23T11:45:00Z"


async def test_a_step_that_arrives_a_second_early_is_timed_as_the_step_it_is(
    rig: Rig, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    # The bus delivers at the step's time. A clock a second behind it must not tell the reporter
    # to reply by 12:59:59, and the status event is not stamped before the step.
    [prompt] = await _prompted(rig, seed_service)

    result = await rig.step(prompt, WorkKind.REMINDER, london(12, 30) - timedelta(seconds=1))

    assert result.action == REMINDED
    [reminder] = await _reminders(neo4j_driver)
    assert reminder["text"].endswith("By 13:00.")
    [changed] = await rig.events("StatusChanged")
    assert changed.payload["at"] == "2026-10-23T11:30:00Z"
    assert changed.payload["after"] == "not-updated"


async def test_a_service_that_never_reported_has_no_status_change_to_announce(
    rig: Rig, seed_service: Seed
) -> None:
    # With no figure at all the board already reads Not updated, so the reminder is sent and no
    # StatusChanged is raised for a change that did not happen.
    [prompt] = await _prompted(rig, seed_service, figure_at=None)

    result = await rig.step(prompt, WorkKind.REMINDER, london(12, 30))

    assert result.action == REMINDED
    assert len(_of_type(await rig.events("SendMessage"), "C8")) == 1
    assert await rig.events("StatusChanged") == []


# --- 2 The phone task at +60, 3 the escalation at +90 --------------------------------------------


async def test_the_phone_task_is_raised_on_capacity_events(rig: Rig, seed_service: Seed) -> None:
    [prompt] = await _prompted(rig, seed_service)

    result = await rig.step(prompt, WorkKind.PHONE_TASK, london(13, 0))

    assert result.action == PHONE_TASK_RAISED
    assert result.communication_id is None
    [task] = await rig.events("PhoneTaskRaised")
    assert task.topic == "capacity.events"
    assert task.session_id == SERVICE
    assert task.payload == {
        "service_id": SERVICE,
        "due_at": "2026-10-23T11:00:00Z",
        "at": "2026-10-23T12:00:00Z",
    }
    assert (await rig.work(prompt, WorkKind.PHONE_TASK)).status == DONE
    # No text goes to anyone at this step: advisors are tasked, the reporter is not chased again.
    assert _of_type(await rig.events("SendMessage"), "C8") == []


async def test_the_escalation_goes_to_the_shift_lead_on_alerts_events(
    rig: Rig, seed_service: Seed
) -> None:
    [prompt] = await _prompted(rig, seed_service)

    result = await rig.step(prompt, WorkKind.ESCALATE_TO_LEAD, london(13, 30))

    assert result.action == ESCALATED
    [escalation] = await rig.events("ReportEscalated")
    assert escalation.topic == "alerts.events"
    assert escalation.session_id is None
    assert escalation.payload == {
        "service_id": SERVICE,
        "due_at": "2026-10-23T11:00:00Z",
        "at": "2026-10-23T12:30:00Z",
    }
    assert (await rig.work(prompt, WorkKind.ESCALATE_TO_LEAD)).status == DONE


async def test_the_whole_ladder_runs_in_order_when_nobody_replies(
    rig: Rig, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    [prompt] = await _prompted(rig, seed_service)

    actions = [
        (await rig.step(prompt, kind, at)).action
        for kind, at in (
            (WorkKind.REMINDER, london(12, 30)),
            (WorkKind.PHONE_TASK, london(13, 0)),
            (WorkKind.ESCALATE_TO_LEAD, london(13, 30)),
        )
    ]

    assert actions == [REMINDED, PHONE_TASK_RAISED, ESCALATED]
    assert await _ladder_statuses(rig, prompt) == {
        WorkKind.REMINDER: DONE,
        WorkKind.PHONE_TASK: DONE,
        WorkKind.ESCALATE_TO_LEAD: DONE,
    }
    assert len(await _reminders(neo4j_driver)) == 1
    # The next prompt is still armed: the ladder never touches prompt-due.
    [next_prompt] = await rig.works(SERVICE, WorkKind.PROMPT_DUE)
    assert (next_prompt.status, next_prompt.due_at) == (SCHEDULED, london(14, 0))


# --- 4 A report at any point stops the rest ------------------------------------------------------


async def test_a_report_after_the_reminder_cancels_the_phone_task_and_the_escalation(
    rig: Rig, seed_service: Seed
) -> None:
    [prompt] = await _prompted(rig, seed_service)
    await rig.step(prompt, WorkKind.REMINDER, london(12, 30))
    phone = await rig.work(prompt, WorkKind.PHONE_TASK)
    lead = await rig.work(prompt, WorkKind.ESCALATE_TO_LEAD)

    await rig.report(london(12, 40), value=3)

    assert await _ladder_statuses(rig, prompt) == {
        WorkKind.REMINDER: DONE,
        WorkKind.PHONE_TASK: CANCELLED,
        WorkKind.ESCALATE_TO_LEAD: CANCELLED,
    }
    cancels = await rig.events("CancelWork")
    assert sorted(m.id for m in cancels) == sorted([f"cancel-{phone.id}", f"cancel-{lead.id}"])
    assert sorted(m.payload["work_id"] for m in cancels) == sorted([phone.id, lead.id])
    assert {m.topic for m in cancels} == {"scheduled.work"}
    # The 13:00 step, when the bus still delivers it, does nothing.
    result = await rig.run(phone, london(13, 0))
    assert result.action == IGNORED
    assert await rig.events("PhoneTaskRaised") == []
    # The next prompt is left alone.
    [next_prompt] = await rig.works(SERVICE, WorkKind.PROMPT_DUE)
    assert next_prompt.status == SCHEDULED


async def test_a_report_before_the_reminder_cancels_every_step(
    rig: Rig, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    [prompt] = await _prompted(rig, seed_service)

    await rig.report(london(12, 10), value=2)

    assert await _ladder_statuses(rig, prompt) == {
        WorkKind.REMINDER: CANCELLED,
        WorkKind.PHONE_TASK: CANCELLED,
        WorkKind.ESCALATE_TO_LEAD: CANCELLED,
    }
    assert len(await rig.events("CancelWork")) == 3
    result = await rig.step(prompt, WorkKind.REMINDER, london(12, 30))
    assert result.action == IGNORED
    assert await _reminders(neo4j_driver) == []
    assert [
        m for m in await rig.events("StatusChanged") if m.payload["at"].endswith("11:30:00Z")
    ] == []


async def test_a_confirmed_figure_stops_the_ladder_as_a_number_does(
    rig: Rig, seed_service: Seed
) -> None:
    [prompt] = await _prompted(rig, seed_service)
    await rig.step(prompt, WorkKind.REMINDER, london(12, 30))
    rig.clock.set(london(12, 40))
    confirm = ConfirmCapacity(rig.factory, rig.clock, rig.ids, DriverIdempotencyStore(rig.driver))

    await confirm.execute(
        ConfirmCapacityCommand(
            idempotency_key="confirm-1",
            actor=Actor(
                role=Role.REPORTER,
                practitioner_id="prac-1",
                device_id=None,
                channel="sms",
                service_ids=frozenset({SERVICE}),
                tenant_id=ACTOR_TENANT,
            ),
            service_id=SERVICE,
            source=ReportSource.TEXT,
            performer_role_id="role-1",
        )
    )

    assert await _ladder_statuses(rig, prompt) == {
        WorkKind.REMINDER: DONE,
        WorkKind.PHONE_TASK: CANCELLED,
        WorkKind.ESCALATE_TO_LEAD: CANCELLED,
    }


async def test_a_report_made_before_the_prompt_does_not_stop_its_ladder(
    rig: Rig, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    # 5: a figure at 11:50 answers nothing the 12:00 prompt asked.
    await seed_service(virtual_ward())
    await seed_people(rig.factory, reporter(1, PHONE_HASH_1))
    await rig.report(london(11, 50), value=4)
    result = await rig.prompt(london(12, 0))
    [prompt] = result.communication_ids

    assert await _ladder_statuses(rig, prompt) == {
        WorkKind.REMINDER: SCHEDULED,
        WorkKind.PHONE_TASK: SCHEDULED,
        WorkKind.ESCALATE_TO_LEAD: SCHEDULED,
    }
    reminded = await rig.step(prompt, WorkKind.REMINDER, london(12, 30))

    assert reminded.action == REMINDED
    assert len(await _reminders(neo4j_driver)) == 1
    assert (await rig.work(prompt, WorkKind.PHONE_TASK)).status == SCHEDULED
    assert [m for m in await rig.events("CancelWork")] == []


async def test_a_figure_back_dated_to_before_the_prompt_does_not_stop_its_ladder(
    rig: Rig, seed_service: Seed
) -> None:
    # An advisor who phoned a service records the call afterwards. The figure is timed 11:50, so it
    # does not answer the 12:00 prompt, and the ladder carries on.
    [prompt] = await _prompted(rig, seed_service)

    await rig.report(london(12, 40), value=4, effective_at=london(11, 50))

    assert await _ladder_statuses(rig, prompt) == {
        WorkKind.REMINDER: SCHEDULED,
        WorkKind.PHONE_TASK: SCHEDULED,
        WorkKind.ESCALATE_TO_LEAD: SCHEDULED,
    }


async def test_a_figure_back_dated_to_after_the_prompt_stops_its_ladder(
    rig: Rig, seed_service: Seed
) -> None:
    [prompt] = await _prompted(rig, seed_service)

    await rig.report(london(12, 40), value=4, effective_at=london(12, 20))

    assert set((await _ladder_statuses(rig, prompt)).values()) == {CANCELLED}


async def test_a_figure_timed_exactly_at_the_due_time_answers_it(
    rig: Rig, seed_service: Seed
) -> None:
    [prompt] = await _prompted(rig, seed_service)

    await rig.report(london(12, 40), value=4, effective_at=london(12, 0))

    assert set((await _ladder_statuses(rig, prompt)).values()) == {CANCELLED}


async def test_a_report_for_one_service_leaves_another_services_ladder_alone(
    rig: Rig, uow_factory: UnitOfWorkFactory, seed_service: Seed
) -> None:
    [prompt] = await _prompted(rig, seed_service)
    other = virtual_ward("vw-respiratory", name="Virtual ward · respiratory")
    await seed_service(other)
    await seed_people(rig.factory, reporter(2, PHONE_HASH_2, "vw-respiratory"))
    await seed_report(rig.factory, london(10, 5), service_id="vw-respiratory", report_id="seed-2")
    other_rig = dataclasses.replace(rig, service_id="vw-respiratory")
    [other_prompt] = (await other_rig.prompt(london(12, 0))).communication_ids

    await rig.report(london(12, 40), value=3)

    assert set((await _ladder_statuses(rig, prompt)).values()) == {CANCELLED}
    assert set((await _ladder_statuses(rig, other_prompt)).values()) == {SCHEDULED}


async def test_a_report_stops_the_ladder_of_every_reporter_of_the_service(
    rig: Rig, seed_service: Seed
) -> None:
    prompts = await _prompted(rig, seed_service, reporters=2)

    await rig.report(london(12, 40), value=3)

    for prompt in prompts:
        assert set((await _ladder_statuses(rig, prompt)).values()) == {CANCELLED}
    assert len(await rig.events("CancelWork")) == 6


async def test_a_report_stops_the_ladder_of_a_service_nobody_could_be_texted_for(
    rig: Rig, seed_service: Seed
) -> None:
    # No reporter has a phone: the ladder is about the service itself (DEC-115 item 15).
    await seed_service(virtual_ward())
    await seed_report(rig.factory, london(10, 5))
    await rig.prompt(london(12, 0))
    assert len(await rig.works(SERVICE, WorkKind.PHONE_TASK)) == 1

    await rig.report(london(12, 40), value=3, performer=False)

    assert set((await _ladder_statuses(rig, SERVICE)).values()) == {CANCELLED}
    [next_prompt] = await rig.works(SERVICE, WorkKind.PROMPT_DUE)
    assert next_prompt.status == SCHEDULED


async def test_a_ladder_a_report_did_not_cancel_stops_itself_at_its_step(
    rig: Rig, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    # A figure written without going through record_report (so nothing cancelled the steps) is
    # still seen at the step: prompt answered, so the step is done, nothing is sent, and the steps
    # after it are cancelled.
    [prompt] = await _prompted(rig, seed_service)
    await seed_report(rig.factory, london(12, 20), report_id="late-report")
    before = await _counts(neo4j_driver)

    result = await rig.step(prompt, WorkKind.REMINDER, london(12, 30))

    assert result.action == STOPPED
    assert await _ladder_statuses(rig, prompt) == {
        WorkKind.REMINDER: DONE,
        WorkKind.PHONE_TASK: CANCELLED,
        WorkKind.ESCALATE_TO_LEAD: CANCELLED,
    }
    assert await _reminders(neo4j_driver) == []
    assert await rig.events("StatusChanged") == []
    assert len(await rig.events("CancelWork")) == 2
    after = await _counts(neo4j_driver)
    assert after["Communication"] == before["Communication"]
    assert after["LinkToken"] == before["LinkToken"]


async def test_a_step_that_finds_the_prompt_answered_at_a_later_step_stops_there_too(
    rig: Rig, seed_service: Seed
) -> None:
    [prompt] = await _prompted(rig, seed_service)
    await rig.step(prompt, WorkKind.REMINDER, london(12, 30))
    await seed_report(rig.factory, london(12, 50), report_id="late-report")

    result = await rig.step(prompt, WorkKind.PHONE_TASK, london(13, 0))

    assert result.action == STOPPED
    assert await rig.events("PhoneTaskRaised") == []
    assert (await rig.work(prompt, WorkKind.ESCALATE_TO_LEAD)).status == CANCELLED
    assert (await rig.work(prompt, WorkKind.REMINDER)).status == DONE


# --- 6 Replays, and work that is not scheduled ---------------------------------------------------


async def test_the_same_step_twice_is_a_replay_and_changes_nothing(
    rig: Rig, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    [prompt] = await _prompted(rig, seed_service)
    work = await rig.work(prompt, WorkKind.REMINDER)
    first = await rig.run(work, london(12, 30))
    counts = await _counts(neo4j_driver)

    second = await rig.run(work, london(12, 31))

    assert first.action == REMINDED
    assert second.replayed is True
    assert dataclasses.replace(second, replayed=False) == first
    assert await _counts(neo4j_driver) == counts
    assert len(await _reminders(neo4j_driver)) == 1


async def test_a_command_key_used_for_another_step_is_a_conflict(
    rig: Rig, seed_service: Seed
) -> None:
    [prompt] = await _prompted(rig, seed_service)
    reminder = await rig.work(prompt, WorkKind.REMINDER)
    phone = await rig.work(prompt, WorkKind.PHONE_TASK)
    await rig.run(reminder, london(12, 30))

    with pytest.raises(Conflict):
        await rig.run(phone, london(13, 0), key=reminder.id)

    assert await rig.events("PhoneTaskRaised") == []
    assert (await rig.work(prompt, WorkKind.PHONE_TASK)).status == SCHEDULED


async def test_work_that_is_not_scheduled_is_ignored_and_writes_nothing(
    rig: Rig, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    [prompt] = await _prompted(rig, seed_service)
    done = await rig.work(prompt, WorkKind.REMINDER)
    await rig.run(done, london(12, 30))
    await rig.report(london(12, 40), value=3)
    cancelled = await rig.work(prompt, WorkKind.PHONE_TASK)
    counts = await _counts(neo4j_driver)

    again = await rig.run(done, london(12, 31), key="another-key-for-done")
    skipped = await rig.run(cancelled, london(13, 0))

    assert again.action == IGNORED
    assert skipped.action == IGNORED
    assert await _counts(neo4j_driver) == counts
    assert (await rig.work(prompt, WorkKind.PHONE_TASK)).status == CANCELLED


async def test_two_phone_tasks_for_one_service_raise_one_event(
    rig: Rig, seed_service: Seed
) -> None:
    # Each reporter's prompt has its own ladder, so a service with two reporters has two phone
    # tasks at +60. Advisors get one task and the lead one escalation for the missed report.
    first, second = await _prompted(rig, seed_service, reporters=2)

    a = await rig.step(first, WorkKind.PHONE_TASK, london(13, 0))
    b = await rig.step(second, WorkKind.PHONE_TASK, london(13, 0))
    c = await rig.step(first, WorkKind.ESCALATE_TO_LEAD, london(13, 30))
    d = await rig.step(second, WorkKind.ESCALATE_TO_LEAD, london(13, 30))

    assert [a.action, b.action, c.action, d.action] == [
        PHONE_TASK_RAISED,
        IGNORED,
        ESCALATED,
        IGNORED,
    ]
    assert len(await rig.events("PhoneTaskRaised")) == 1
    assert len(await rig.events("ReportEscalated")) == 1
    # The duplicate step is finished, so the bus does not deliver it again.
    assert (await rig.work(second, WorkKind.PHONE_TASK)).status == DONE
    assert (await rig.work(second, WorkKind.ESCALATE_TO_LEAD)).status == DONE


async def test_each_reporter_is_reminded_but_the_status_changes_once(
    rig: Rig, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    first, second = await _prompted(rig, seed_service, reporters=2)

    a = await rig.step(first, WorkKind.REMINDER, london(12, 30))
    b = await rig.step(second, WorkKind.REMINDER, london(12, 30))

    assert (a.action, b.action) == (REMINDED, REMINDED)
    reminders = await _reminders(neo4j_driver)
    assert sorted(r["role"] for r in reminders) == ["role-1", "role-2"]
    assert len(await rig.events("StatusChanged")) == 1
    tokens = [
        LINK_AT_END.search(rig.opened(m)["text"])
        for m in _of_type(await rig.events("SendMessage"), "C8")
    ]
    assert len({t.group(1) for t in tokens if t}) == 2


# --- A service that cannot be chased by text, and a reporter who has gone ------------------------


async def test_a_service_ladder_with_nobody_to_text_still_raises_the_status_and_the_alerts(
    rig: Rig, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(virtual_ward())
    await seed_report(rig.factory, london(10, 5))
    result = await rig.prompt(london(12, 0))
    assert result.sent is False

    reminded = await rig.step(SERVICE, WorkKind.REMINDER, london(12, 30))
    phone = await rig.step(SERVICE, WorkKind.PHONE_TASK, london(13, 0))
    lead = await rig.step(SERVICE, WorkKind.ESCALATE_TO_LEAD, london(13, 30))

    assert (reminded.action, phone.action, lead.action) == (
        REMINDED,
        PHONE_TASK_RAISED,
        ESCALATED,
    )
    assert reminded.communication_id is None
    assert await _reminders(neo4j_driver) == []
    assert await rig.events("SendMessage") == []
    [changed] = await rig.events("StatusChanged")
    assert changed.payload["after"] == "not-updated"
    assert len(await rig.events("PhoneTaskRaised")) == 1
    assert len(await rig.events("ReportEscalated")) == 1


@pytest.mark.parametrize("what", ["role-ended", "holder-without-phone", "holder-inactive"])
async def test_a_reporter_who_can_no_longer_be_texted_is_not_reminded_but_the_service_is_flagged(
    what: str, rig: Rig, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    [prompt] = await _prompted(rig, seed_service)
    practitioner, role = reporter(1, PHONE_HASH_1)
    if what == "role-ended":
        role = dataclasses.replace(role, active=False)
    elif what == "holder-without-phone":
        practitioner = dataclasses.replace(practitioner, phone_hash=None)
    else:
        practitioner = dataclasses.replace(practitioner, active=False)
    await seed_people(rig.factory, (practitioner, role))

    result = await rig.step(prompt, WorkKind.REMINDER, london(12, 30))

    assert result.action == REMINDED
    assert result.communication_id is None
    assert await _reminders(neo4j_driver) == []
    assert _of_type(await rig.events("SendMessage"), "C8") == []
    assert len(await rig.events("StatusChanged")) == 1
    assert (await rig.work(prompt, WorkKind.REMINDER)).status == DONE


async def test_stopping_one_ladder_leaves_the_ladder_of_a_later_prompt_of_the_service(
    rig: Rig, seed_service: Seed
) -> None:
    # No reporter has a phone, so each prompt's ladder is about the service itself. Stopping the
    # 12:00 ladder must not touch the 14:00 one, which is about the same subject.
    await seed_service(virtual_ward())
    await seed_report(rig.factory, london(10, 5))
    await rig.prompt(london(12, 0))
    await rig.prompt(london(14, 0))
    await seed_report(rig.factory, london(12, 20), report_id="late-report")

    [first_reminder, _second_reminder] = await rig.works(SERVICE, WorkKind.REMINDER)
    assert first_reminder.due_at == london(12, 30)

    result = await rig.run(first_reminder, london(12, 30))

    assert result.action == STOPPED
    ladders = {
        (w.kind, w.due_at): w.status
        for kind in (WorkKind.REMINDER, WorkKind.PHONE_TASK, WorkKind.ESCALATE_TO_LEAD)
        for w in await rig.works(SERVICE, kind)
    }
    assert ladders == {
        (WorkKind.REMINDER, london(12, 30)): DONE,
        (WorkKind.PHONE_TASK, london(13, 0)): CANCELLED,
        (WorkKind.ESCALATE_TO_LEAD, london(13, 30)): CANCELLED,
        (WorkKind.REMINDER, london(14, 30)): SCHEDULED,
        (WorkKind.PHONE_TASK, london(15, 0)): SCHEDULED,
        (WorkKind.ESCALATE_TO_LEAD, london(15, 30)): SCHEDULED,
    }


# --- Services that no longer need chasing --------------------------------------------------------


async def test_a_service_that_has_been_deactivated_is_not_chased(
    rig: Rig, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    [prompt] = await _prompted(rig, seed_service)
    await seed_service(virtual_ward(active=False))

    result = await rig.step(prompt, WorkKind.REMINDER, london(12, 30))

    assert result.action == STOPPED
    assert await _reminders(neo4j_driver) == []
    assert set((await _ladder_statuses(rig, prompt)).values()) == {DONE, CANCELLED}
    assert await rig.events("StatusChanged") == []


async def test_a_suspended_service_is_not_chased(
    rig: Rig, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    [prompt] = await _prompted(rig, seed_service)
    await seed_service(
        flags=(
            ServiceFlag(
                service_id=SERVICE,
                code=SERVICE_FLAG_SUSPENDED,
                active=True,
                reason="suspended for the test",
                actor_id="lead-1",
                at=london(11, 0),
            ),
        )
    )

    result = await rig.step(prompt, WorkKind.PHONE_TASK, london(13, 0))

    assert result.action == STOPPED
    assert await rig.events("PhoneTaskRaised") == []
    assert (await rig.work(prompt, WorkKind.PHONE_TASK)).status == DONE
    assert (await rig.work(prompt, WorkKind.ESCALATE_TO_LEAD)).status == CANCELLED


async def test_the_step_is_still_run_when_the_service_is_out_of_hours(
    rig: Rig, seed_service: Seed
) -> None:
    # domain-rules 1.5 has no out-of-hours exception: a missed report is chased on schedule. This
    # service closes at 18:45, so the phone task for the 18:00 prompt (19:00) falls after closing.
    closing_early = virtual_ward(
        available_times=(AvailableTime.every_day(time(8, 0), time(18, 45)),)
    )
    await seed_service(closing_early)
    await seed_people(rig.factory, reporter(1, PHONE_HASH_1))
    await seed_report(rig.factory, london(16, 10))
    [prompt] = (await rig.prompt(london(18, 0))).communication_ids

    result = await rig.step(prompt, WorkKind.PHONE_TASK, london(19, 0))

    assert result.action == PHONE_TASK_RAISED
    [task] = await rig.events("PhoneTaskRaised")
    assert task.payload["due_at"] == "2026-10-23T17:00:00Z"


# --- Refusals ------------------------------------------------------------------------------------


async def test_an_unknown_work_id_is_not_found_and_writes_nothing(
    rig: Rig, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _prompted(rig, seed_service)
    counts = await _counts(neo4j_driver)

    with pytest.raises(NotFound):
        await rig.ladder.execute(
            LadderStepCommand(idempotency_key="k", actor=SYSTEM_ACTOR, work_id="no-such-work")
        )

    assert await _counts(neo4j_driver) == counts


async def test_work_that_is_not_a_ladder_step_is_refused(rig: Rig, seed_service: Seed) -> None:
    await _prompted(rig, seed_service)
    [prompt_due] = await rig.works(SERVICE, WorkKind.PROMPT_DUE)

    with pytest.raises(ValidationFailed) as refused:
        await rig.run(prompt_due, london(14, 0))

    assert refused.value.field == "kind"
    assert (await rig.works(SERVICE, WorkKind.PROMPT_DUE))[0].status == SCHEDULED


async def test_work_about_a_service_that_does_not_exist_is_not_found(
    rig: Rig, neo4j_driver: AsyncDriver, uow_factory: UnitOfWorkFactory, seed_service: Seed
) -> None:
    await _prompted(rig, seed_service)
    async with uow_factory() as uow:
        orphan = await schedule_work(
            uow,
            rig.ids,
            kind=WorkKind.PHONE_TASK,
            about_id="no-such-service",
            due_at=london(13, 0),
            now=london(12, 0),
        )
        await uow.commit()
    counts = await _counts(neo4j_driver)

    with pytest.raises(NotFound):
        await rig.run(orphan, london(13, 0))

    assert await _counts(neo4j_driver) == counts
    async with uow_factory() as uow:
        assert (await uow.scheduled_work.get(orphan.id)).status == SCHEDULED


async def test_work_about_a_message_with_no_service_is_not_found(
    rig: Rig, neo4j_driver: AsyncDriver, uow_factory: UnitOfWorkFactory, seed_service: Seed
) -> None:
    await _prompted(rig, seed_service)
    async with uow_factory() as uow:
        await uow.communications.add(
            Communication(
                id="no-service-comm",
                message_id="C1",
                channel=Channel.TEXT,
                recipient_role_id=None,
                about_id=None,
                payload_text="DIUCS: a message about nothing",
                sent_at=london(12, 0),
                delivery_status="queued",
            )
        )
        orphan = await schedule_work(
            uow,
            rig.ids,
            kind=WorkKind.REMINDER,
            about_id="no-service-comm",
            due_at=london(12, 30),
            now=london(12, 0),
        )
        await uow.commit()
    counts = await _counts(neo4j_driver)

    with pytest.raises(NotFound):
        await rig.run(orphan, london(12, 30))

    assert await _counts(neo4j_driver) == counts


async def test_a_failure_part_way_leaves_nothing_behind(
    rig: Rig, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    [prompt] = await _prompted(rig, seed_service)
    work = await rig.work(prompt, WorkKind.REMINDER)
    counts = await _counts(neo4j_driver)
    inner = rig.factory

    class FailingAudit:
        def __init__(self, audit: Any) -> None:
            self._audit = audit

        async def append(self, entry: Any) -> None:
            raise RuntimeError("audit write failed")

        def __getattr__(self, name: str) -> Any:
            return getattr(self._audit, name)

    class FailingUnit:
        def __init__(self, unit: UnitOfWork) -> None:
            self._unit = unit

        @property
        def audit(self) -> FailingAudit:
            return FailingAudit(self._unit.audit)

        async def __aenter__(self) -> Self:
            await self._unit.__aenter__()
            return self

        async def __aexit__(self, *exc: Any) -> Any:
            return await self._unit.__aexit__(*exc)

        def __getattr__(self, name: str) -> Any:
            return getattr(self._unit, name)

    failing = build_rig(
        lambda: FailingUnit(inner()),  # type: ignore[arg-type, return-value]
        neo4j_driver,
        rig.tenant,
        ids=rig.ids,
    )

    with pytest.raises(RuntimeError, match="audit write failed"):
        await failing.run(work, london(12, 30))

    assert await _counts(neo4j_driver) == counts
    assert (await rig.work(prompt, WorkKind.REMINDER)).status == SCHEDULED
    assert await rig.events("StatusChanged") == []


# --- Concurrency: the report and the step take the service lock ----------------------------------


class _Gate:
    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()


class _HeldAtCommit:
    """A unit of work that, once it holds its write locks, stops before it commits."""

    def __init__(self, unit: UnitOfWork, gate: _Gate) -> None:
        self._unit = unit
        self._gate = gate

    async def __aenter__(self) -> Self:
        await self._unit.__aenter__()
        return self

    async def __aexit__(self, *exc: Any) -> Any:
        return await self._unit.__aexit__(*exc)

    async def commit(self) -> None:
        self._gate.entered.set()
        await self._gate.release.wait()
        await self._unit.commit()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._unit, name)


async def test_a_step_waits_for_a_report_that_holds_the_service_and_then_stops(
    rig: Rig, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    # A report holds the service lock and has not committed. The step must not read the service's
    # figure until the report is in, or it would remind a service that has just reported (H-13).
    # The interleaving is forced with a held commit, not left to timing (lesson L94).
    [prompt] = await _prompted(rig, seed_service)
    work = await rig.work(prompt, WorkKind.REMINDER)
    gate = _Gate()
    holding = build_rig(
        lambda: _HeldAtCommit(rig.factory(), gate),  # type: ignore[arg-type, return-value]
        neo4j_driver,
        rig.tenant,
        ids=rig.ids,
    )
    report = asyncio.ensure_future(holding.report(london(12, 25), value=3))
    await asyncio.wait_for(gate.entered.wait(), timeout=30)

    step = asyncio.ensure_future(rig.run(work, london(12, 30)))
    try:
        done, _pending = await asyncio.wait({step}, timeout=1)
        assert done == set()
    finally:
        # Whatever the check found, the held report must finish, or its locks block the next test.
        gate.release.set()
    await report
    result = await asyncio.wait_for(step, timeout=30)

    assert result.action == IGNORED
    assert await _reminders(neo4j_driver) == []
    assert (await rig.work(prompt, WorkKind.REMINDER)).status == CANCELLED


async def test_racing_deliveries_of_one_step_send_one_reminder(
    rig: Rig, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    [prompt] = await _prompted(rig, seed_service)
    work = await rig.work(prompt, WorkKind.REMINDER)
    rig.clock.set(london(12, 30))

    results = await asyncio.gather(
        *(
            rig.ladder.execute(
                LadderStepCommand(
                    idempotency_key=f"delivery-{n}", actor=SYSTEM_ACTOR, work_id=work.id
                )
            )
            for n in range(8)
        )
    )

    assert sorted(r.action for r in results) == [IGNORED] * 7 + [REMINDED]
    assert len(await _reminders(neo4j_driver)) == 1
    assert len(await rig.events("StatusChanged")) == 1


# --- Grouped prompts: each service keeps its own ladder (U04, DEC-158, H-16) ------------------


async def test_a_grouped_prompt_gives_each_service_its_own_reminder_and_ladder(
    rig: Rig, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    # One phone holds a role in two services, so one C9 text covers both at 12:00. Each service
    # keeps its own ladder: its own reminder names only it, carries its own link, and a report for
    # one service stops that ladder and not the other.
    await seed_service(
        virtual_ward(), virtual_ward("vw-respiratory", name="Virtual ward · respiratory")
    )
    practitioner, frailty_role = reporter(1, PHONE_HASH_1)
    respiratory_role = dataclasses.replace(frailty_role, id="role-2", service_id="vw-respiratory")
    async with rig.factory() as uow:
        await uow.people.save_practitioner(practitioner)
        await uow.people.save_role(frailty_role)
        await uow.people.save_role(respiratory_role)
        await uow.commit()
    await seed_report(rig.factory, london(10, 5))
    await seed_report(
        rig.factory, london(10, 5), service_id="vw-respiratory", report_id="seed-respiratory"
    )
    respiratory = dataclasses.replace(rig, service_id="vw-respiratory")
    first = await rig.prompt(london(12, 0))
    second = await respiratory.prompt(london(12, 0))
    assert first.grouped_service_ids == ("vw-frailty", "vw-respiratory")
    [frailty_prompt] = first.communication_ids
    [respiratory_prompt] = second.communication_ids

    await rig.step(frailty_prompt, WorkKind.REMINDER, london(12, 30))
    await respiratory.step(respiratory_prompt, WorkKind.REMINDER, london(12, 30))

    reminders = {row["service"]: row for row in await _reminders(neo4j_driver)}
    assert set(reminders) == {"vw-frailty", "vw-respiratory"}
    assert reminders["vw-frailty"]["role"] == "role-1"
    assert reminders["vw-respiratory"]["role"] == "role-2"
    assert "Virtual ward · frailty has not updated" in reminders["vw-frailty"]["text"]
    assert "respiratory" not in reminders["vw-frailty"]["text"]
    assert "Virtual ward · respiratory has not updated" in reminders["vw-respiratory"]["text"]
    assert "frailty" not in reminders["vw-respiratory"]["text"]
    for service, row in reminders.items():
        [message] = [
            m
            for m in _of_type(await rig.events("SendMessage"), "C8")
            if m.payload["communication_id"] == row["id"]
        ]
        match = LINK_AT_END.search(rig.opened(message)["text"])
        assert match is not None
        record = await _resolve(neo4j_driver, match.group(1))
        assert record.about_id == row["id"]
        assert service in {"vw-frailty", "vw-respiratory"}
    # A report for one service stops that service's ladder only.
    await rig.report(london(12, 40), value=3)
    assert set((await _ladder_statuses(rig, frailty_prompt)).values()) == {DONE, CANCELLED}
    assert (await _ladder_statuses(rig, respiratory_prompt))[WorkKind.PHONE_TASK] == SCHEDULED
