"""The alert runners against the Service Bus emulator (B1 task 5, N2): the `notifier` subscription
of `alerts.events` hands an escalation to `NotifyShiftLeads`, which queues a push for the tenant's
shift lead, and the `alert-evaluator` subscription of `capacity.events` hands a status change to
`AlertEvaluator`, which marks it handled. Both publish as the adapter does (qualified ids, the
tenant property). Ids are unique per run (lessons L6, L101); the emulator is shared, so the test
holds its lock and filters by its own message ids."""

import asyncio
import uuid
from datetime import UTC, datetime, time

import pytest

from diucs.adapters.inbound.workers.alert_consumers import alert_runners
from diucs.adapters.inbound.workers.outbox_relay import StaticTenants
from diucs.adapters.outbound.bus_servicebus.service_bus import to_service_bus_message
from diucs.adapters.outbound.content_seal.aes_gcm import AesGcmContentSealer
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.application.ports.outbound.event_bus import BusMessage
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.alerts import AlertEvaluator
from diucs.application.use_cases.notify_escalations import NotifyShiftLeads
from diucs.domain.codes import (
    Cadence,
    Channel,
    Measure,
    PractitionerRoleCode,
    ServiceCategory,
)
from diucs.domain.model.people import Practitioner, PractitionerRole
from diucs.domain.model.service import AvailableTime, ServiceProfile
from tests.support.servicebus import client, take_emulator_lock

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio(loop_scope="session"),
    pytest.mark.servicebus,
    pytest.mark.exclusive,
]

NOW = datetime(2026, 10, 31, 9, 0, tzinfo=UTC)
SERVICE = ServiceProfile(
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


async def test_an_escalation_and_a_status_change_reach_their_use_cases_through_the_bus(
    uow_factory: UnitOfWorkFactory, tenant_id: str
) -> None:
    async with uow_factory() as uow:
        await uow.services.save(SERVICE)
        await uow.people.save_practitioner(
            Practitioner(id="prac-lead-1", active=True, display_name="Lead 1", phone_hash=None)
        )
        await uow.people.save_role(
            PractitionerRole(
                id="role-lead-1",
                practitioner_id="prac-lead-1",
                service_id=None,
                code=PractitionerRoleCode.SHIFT_LEAD,
                active=True,
                channel=Channel.PUSH,
                period_start=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
        await uow.commit()
    clock = FixedClock(NOW)
    sealer = AesGcmContentSealer(FixedSecretStore({"link-token": b"x" * 40}))
    escalation_id = f"escalation-{uuid.uuid4()}"
    status_id = f"status-{uuid.uuid4()}"
    release = await take_emulator_lock()
    try:
        async with client() as sb:
            runners = alert_runners(
                sb,
                AlertEvaluator(uow_factory, SequentialIds("a")),
                NotifyShiftLeads(uow_factory, SequentialIds("n"), clock, sealer),
                StaticTenants([tenant_id]),
            )
            async with sb.get_topic_sender("alerts.events") as sender:
                await sender.send_messages(
                    to_service_bus_message(
                        BusMessage(
                            id=escalation_id,
                            topic="alerts.events",
                            event_type="ReportEscalated",
                            payload={
                                "service_id": "ucr-west",
                                "due_at": "2026-10-31T07:30:00Z",
                                "at": "2026-10-31T09:00:00Z",
                            },
                            tenant_id=tenant_id,
                        )
                    )
                )
            async with sb.get_topic_sender("capacity.events") as sender:
                await sender.send_messages(
                    to_service_bus_message(
                        BusMessage(
                            id=status_id,
                            topic="capacity.events",
                            event_type="StatusChanged",
                            payload={
                                "service_id": "ucr-west",
                                "before": "accepting",
                                "after": "not-accepting",
                                "at": "2026-10-31T09:00:00Z",
                            },
                            session_id="ucr-west",
                            tenant_id=tenant_id,
                        )
                    )
                )
            stop = asyncio.Event()
            tasks = [asyncio.create_task(r.run(stop)) for r in runners]
            try:
                async with asyncio.timeout(90):
                    while True:
                        async with uow_factory() as uow:
                            told = [
                                m
                                for m in await uow.outbox.pending(limit=1000)
                                if m.event_type == "SendMessage"
                            ]
                            evaluated = await uow.processed.seen(status_id, "alert-evaluator")
                        if told and evaluated:
                            break
                        await asyncio.sleep(0.5)
            finally:
                stop.set()
                # A session receiver that is waiting for a session takes its own time to see the
                # stop (the board's does the same): wait, then cancel what is left.
                _, pending = await asyncio.wait(tasks, timeout=75)
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
    finally:
        release()
    assert [m.payload["recipient_role_id"] for m in told] == ["role-lead-1"]
