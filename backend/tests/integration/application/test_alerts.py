"""Integration tests for the alert evaluator, the not-updated checks, acknowledge, snooze and
escalation (U34), against the real Neo4j.

The subscriptions are stored as U33 stores them; every assertion reads back through a fresh unit of
work. Sample values only: no patient, no reporter name, no number.
"""

from datetime import UTC, datetime, time

import pytest
from neo4j import AsyncDriver

from diucs.adapters.outbound.audit_neo4j.audit_log import ensure_audit_head
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.application.actor import Actor
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.alerts import (
    AcknowledgeAlert,
    AcknowledgeAlertCommand,
    AlertEvaluator,
    EscalateAlert,
    EscalateAlertCommand,
    NotUpdatedCheck,
    NotUpdatedCheckCommand,
    SnoozeAlert,
    SnoozeAlertCommand,
    StatusChangedCommand,
    check_about,
)
from diucs.application.work import SCHEDULED, WorkKind
from diucs.domain.codes import AlertKind, Role, Status
from diucs.domain.model.alerts import AlertRecord, AlertSubscription
from diucs.domain.model.service import AvailableTime, ServiceProfile
from diucs.domain.rules.alerts import AlertPreferences
from tests.support.actors import ACTOR_TENANT
from tests.support.ladder_rig import seed_report
from tests.support.link_rig import ucr_west

pytestmark = pytest.mark.asyncio(loop_scope="session")

SERVICE_ID = "ucr-west"
ALL_KINDS = frozenset(AlertKind)
LEAD_OR_OWNER = Actor(Role.ADVISOR, "prac-1", None, "web", frozenset(), tenant_id=ACTOR_TENANT)
OTHER = Actor(Role.ADVISOR, "prac-9", None, "web", frozenset(), tenant_id=ACTOR_TENANT)


def at(hour: int, minute: int) -> datetime:
    return datetime(2026, 10, 29, hour, minute, tzinfo=UTC)


def prefs(
    *,
    kinds: frozenset[AlertKind] = ALL_KINDS,
    not_updated_hours: int = 2,
    quiet: bool = False,
    ack_minutes: int = 15,
) -> AlertPreferences:
    return AlertPreferences(
        kinds=kinds,
        not_updated_hours=not_updated_hours,
        quiet_hours=(time(22, 0), time(6, 0)) if quiet else None,
        quiet_critical_only=True,
        ack_minutes=ack_minutes,
    )


def subscription(
    practitioner: str, preferences: AlertPreferences, deputy: str | None
) -> AlertSubscription:
    return AlertSubscription(
        practitioner_id=practitioner,
        preferences=preferences,
        deputy_id=deputy,
        daily_summary=False,
        weekly_summary=False,
        updated_at=at(9, 0),
    )


def in_hours_profile() -> ServiceProfile:
    """UCR West open from 08:00 to 23:30 every day, so 23:00 is inside its hours."""
    return ucr_west(
        SERVICE_ID, available_times=(AvailableTime.every_day(time(8, 0), time(23, 30)),)
    )


async def seed(
    uow_factory: UnitOfWorkFactory,
    driver: AsyncDriver,
    *,
    owner: AlertSubscription,
    deputy: AlertSubscription | None = None,
    extra: tuple[AlertSubscription, ...] = (),
) -> None:
    await ensure_audit_head(driver)
    async with uow_factory() as uow:
        await uow.services.save(in_hours_profile())
        await uow.alert_subscriptions.save(owner)
        if deputy is not None:
            await uow.alert_subscriptions.save(deputy)
        for item in extra:
            await uow.alert_subscriptions.save(item)
        await uow.commit()


def evaluator(uow_factory: UnitOfWorkFactory, prefix: str) -> AlertEvaluator:
    return AlertEvaluator(uow_factory, SequentialIds(prefix))


async def change(
    uow_factory: UnitOfWorkFactory,
    message_id: str,
    before: Status | None,
    after: Status,
    when: datetime,
    prefix: str,
) -> None:
    await evaluator(uow_factory, prefix).execute(
        StatusChangedCommand(message_id, SERVICE_ID, before, after, when)
    )


async def alerts_of(uow_factory: UnitOfWorkFactory, owner: str) -> list[AlertRecord]:
    async with uow_factory() as uow:
        return await uow.alerts.open_for_owner(owner)


async def alert_by_id(uow_factory: UnitOfWorkFactory, alert_id: str) -> AlertRecord:
    async with uow_factory() as uow:
        record = await uow.alerts.get(alert_id)
    assert record is not None
    return record


async def outbox_events(uow_factory: UnitOfWorkFactory, event_type: str) -> list[object]:
    async with uow_factory() as uow:
        return [m for m in await uow.outbox.pending(200) if m.event_type == event_type]


async def escalation_work(uow_factory: UnitOfWorkFactory, alert_id: str) -> list[object]:
    async with uow_factory() as uow:
        return list(await uow.scheduled_work.for_about(alert_id, WorkKind.ALERT_ESCALATE))


async def test_an_over_capacity_change_at_1412_raises_one_new_alert_with_a_push_and_a_timer(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed(uow_factory, neo4j_driver, owner=subscription("prac-1", prefs(), None))
    await change(uow_factory, "sc-1", Status.LIMITED, Status.OVER_CAPACITY, at(14, 12), "a1")
    (record,) = await alerts_of(uow_factory, "prac-1")
    assert record.status == "new"
    assert record.kind is AlertKind.OVER_CAPACITY
    assert record.escalation_due_at == at(14, 27)
    push = [
        m
        for m in await outbox_events(uow_factory, "SendMessage")
        if m.payload["message_id"] == "K3"
    ]
    assert len(push) == 1
    assert push[0].payload["recipient_practitioner_id"] == "prac-1"
    assert len(await outbox_events(uow_factory, "AlertRaised")) == 1
    (timer,) = await escalation_work(uow_factory, record.id)
    assert timer.status == SCHEDULED
    assert timer.due_at == at(14, 27)


async def test_at_2300_over_capacity_is_not_sent_to_a_quiet_subscriber_but_service_closed_is(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed(
        uow_factory,
        neo4j_driver,
        owner=subscription(
            "prac-1",
            prefs(kinds=frozenset({AlertKind.OVER_CAPACITY, AlertKind.SERVICE_CLOSED}), quiet=True),
            None,
        ),
    )
    await change(uow_factory, "sc-2a", Status.LIMITED, Status.OVER_CAPACITY, at(23, 0), "a2a")
    assert await alerts_of(uow_factory, "prac-1") == []
    await change(uow_factory, "sc-2b", Status.ACCEPTING, Status.NOT_ACCEPTING, at(23, 0), "a2b")
    kinds = [record.kind for record in await alerts_of(uow_factory, "prac-1")]
    assert kinds == [AlertKind.SERVICE_CLOSED]


async def test_acknowledging_at_1420_closes_the_alert_and_cancels_its_timer(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed(uow_factory, neo4j_driver, owner=subscription("prac-1", prefs(), None))
    await change(uow_factory, "sc-3", Status.LIMITED, Status.OVER_CAPACITY, at(14, 12), "a3")
    (record,) = await alerts_of(uow_factory, "prac-1")
    await AcknowledgeAlert(uow_factory, FixedClock(at(14, 20))).execute(
        AcknowledgeAlertCommand(record.id, LEAD_OR_OWNER)
    )
    assert (await alert_by_id(uow_factory, record.id)).status == "acknowledged"
    (timer,) = await escalation_work(uow_factory, record.id)
    assert timer.status == "cancelled"
    cancels = [
        m
        for m in await outbox_events(uow_factory, "CancelWork")
        if m.payload["work_id"] == timer.id
    ]
    assert len(cancels) == 1
    # The escalation that was due at 14:27 writes nothing now.
    outcome = await EscalateAlert(uow_factory, SequentialIds("e3"), FixedClock(at(14, 27))).execute(
        EscalateAlertCommand(timer.id, record.id)
    )
    assert outcome.acted is False


async def test_without_an_acknowledgement_the_deputy_is_alerted_then_the_lead_once(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed(
        uow_factory,
        neo4j_driver,
        owner=subscription("prac-1", prefs(), "prac-2"),
        deputy=subscription("prac-2", prefs(kinds=frozenset()), None),
    )
    await change(uow_factory, "sc-4", Status.LIMITED, Status.OVER_CAPACITY, at(14, 12), "a4")
    (first,) = await alerts_of(uow_factory, "prac-1")
    (timer,) = await escalation_work(uow_factory, first.id)
    outcome = await EscalateAlert(uow_factory, SequentialIds("e4"), FixedClock(at(14, 27))).execute(
        EscalateAlertCommand(timer.id, first.id)
    )
    assert outcome.escalated_to == "deputy"
    assert (await alert_by_id(uow_factory, first.id)).status == "escalated"
    (deputy_alert,) = await alerts_of(uow_factory, "prac-2")
    assert deputy_alert.part_of_id == first.id
    assert deputy_alert.status == "new"
    (deputy_timer,) = await escalation_work(uow_factory, deputy_alert.id)
    lead = EscalateAlert(uow_factory, SequentialIds("e4b"), FixedClock(at(14, 42)))
    first_run = await lead.execute(EscalateAlertCommand(deputy_timer.id, deputy_alert.id))
    second_run = await lead.execute(EscalateAlertCommand(deputy_timer.id, deputy_alert.id))
    assert first_run.escalated_to == "shift-lead"
    assert second_run.acted is False
    assert len(await outbox_events(uow_factory, "AlertEscalatedToLead")) == 1


async def test_snoozing_at_1420_moves_the_escalation_to_1527_and_the_alert_stays_new(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed(uow_factory, neo4j_driver, owner=subscription("prac-1", prefs(), None))
    await change(uow_factory, "sc-5", Status.LIMITED, Status.OVER_CAPACITY, at(14, 12), "a5")
    (record,) = await alerts_of(uow_factory, "prac-1")
    result = await SnoozeAlert(uow_factory, SequentialIds("s5"), FixedClock(at(14, 20))).execute(
        SnoozeAlertCommand(record.id, LEAD_OR_OWNER)
    )
    assert result.escalation_due_at == at(15, 27)
    stored = await alert_by_id(uow_factory, record.id)
    assert stored.status == "new"
    assert stored.escalation_due_at == at(15, 27)
    live = [w for w in await escalation_work(uow_factory, record.id) if w.status == SCHEDULED]
    assert [w.due_at for w in live] == [at(15, 27)]


async def test_not_updated_at_1230_is_checked_at_1430_and_only_two_hour_subscribers_are_alerted(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed(
        uow_factory,
        neo4j_driver,
        owner=subscription("prac-1", prefs(not_updated_hours=2), None),
        extra=(subscription("prac-3", prefs(not_updated_hours=4), None),),
    )
    await change(uow_factory, "sc-6", Status.ACCEPTING, Status.NOT_UPDATED, at(12, 30), "a6")
    async with uow_factory() as uow:
        checks = await uow.scheduled_work.for_about(
            check_about(SERVICE_ID, 2), WorkKind.NOT_UPDATED_CHECK
        )
        checks_four = await uow.scheduled_work.for_about(
            check_about(SERVICE_ID, 4), WorkKind.NOT_UPDATED_CHECK
        )
    assert [w.due_at for w in checks] == [at(14, 30)]
    assert [w.due_at for w in checks_four] == [at(16, 30)]
    (check_two,) = checks
    raised = await NotUpdatedCheck(
        uow_factory, SequentialIds("n6"), FixedClock(at(14, 30))
    ).execute(NotUpdatedCheckCommand(check_two.id, check_two.about_id))
    assert raised == 1
    assert [a.kind for a in await alerts_of(uow_factory, "prac-1")] == [AlertKind.NOT_UPDATED]
    assert await alerts_of(uow_factory, "prac-3") == []


async def test_a_report_at_1300_means_the_not_updated_check_at_1430_alerts_nobody(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed(
        uow_factory, neo4j_driver, owner=subscription("prac-1", prefs(not_updated_hours=2), None)
    )
    await seed_report(uow_factory, at(13, 0), service_id=SERVICE_ID, value=3)
    await change(uow_factory, "sc-7", Status.ACCEPTING, Status.NOT_UPDATED, at(12, 30), "a7")
    async with uow_factory() as uow:
        (check,) = await uow.scheduled_work.for_about(
            check_about(SERVICE_ID, 2), WorkKind.NOT_UPDATED_CHECK
        )
    raised = await NotUpdatedCheck(
        uow_factory, SequentialIds("n7"), FixedClock(at(14, 30))
    ).execute(NotUpdatedCheckCommand(check.id, check.about_id))
    assert raised == 0
    assert await alerts_of(uow_factory, "prac-1") == []


async def test_the_same_status_changed_message_twice_raises_one_alert(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed(uow_factory, neo4j_driver, owner=subscription("prac-1", prefs(), None))
    await change(uow_factory, "sc-8", Status.LIMITED, Status.OVER_CAPACITY, at(14, 12), "a8")
    again = await evaluator(uow_factory, "a8b").execute(
        StatusChangedCommand("sc-8", SERVICE_ID, Status.LIMITED, Status.OVER_CAPACITY, at(14, 12))
    )
    assert again.duplicate is True
    assert len(await alerts_of(uow_factory, "prac-1")) == 1


async def test_someone_else_cannot_acknowledge_or_snooze_the_alert(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    from diucs.domain.errors import NotAllowed

    await seed(uow_factory, neo4j_driver, owner=subscription("prac-1", prefs(), None))
    await change(uow_factory, "sc-9", Status.LIMITED, Status.OVER_CAPACITY, at(14, 12), "a9")
    (record,) = await alerts_of(uow_factory, "prac-1")
    with pytest.raises(NotAllowed):
        await AcknowledgeAlert(uow_factory, FixedClock(at(14, 20))).execute(
            AcknowledgeAlertCommand(record.id, OTHER)
        )
    with pytest.raises(NotAllowed):
        await SnoozeAlert(uow_factory, SequentialIds("s9"), FixedClock(at(14, 20))).execute(
            SnoozeAlertCommand(record.id, OTHER)
        )
    assert (await alert_by_id(uow_factory, record.id)).status == "new"
