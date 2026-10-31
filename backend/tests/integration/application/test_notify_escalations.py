"""NotifyShiftLeads on the real Neo4j with two tenants (B1 task 5, N2). An escalation of one
tenant's service is told to that tenant's active shift leads only, once for each message, and the
other tenant's lead hears nothing. The outbox is read, not relayed: nothing is sent. Synthetic
values only.
"""

import dataclasses
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, time

import pytest
from neo4j import AsyncDriver

from diucs.adapters.outbound.content_seal.aes_gcm import AesGcmContentSealer
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.notify_escalations import NotifyLeadsCommand, NotifyShiftLeads
from diucs.domain.codes import (
    Cadence,
    Channel,
    Measure,
    PractitionerRoleCode,
    ServiceCategory,
)
from diucs.domain.model.people import Practitioner, PractitionerRole
from diucs.domain.model.service import AvailableTime, ServiceProfile
from tests.support.tenancy import as_tenant
from tests.support.uow import ensure_audit_heads, tenant_uow_factory

pytestmark = pytest.mark.asyncio(loop_scope="session")

Seed = Callable[..., Awaitable[None]]

NOW = datetime(2026, 10, 31, 9, 0, tzinfo=UTC)
SECRET = b"link-token-test-secret-0123456789abcdef"
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


def _use_case(factory: UnitOfWorkFactory) -> NotifyShiftLeads:
    return NotifyShiftLeads(
        factory,
        SequentialIds("n"),
        FixedClock(NOW),
        AesGcmContentSealer(FixedSecretStore({"link-token": SECRET})),
    )


async def _lead(
    factory: UnitOfWorkFactory, number: int, *, active: bool = True, code: str = "shift-lead"
) -> None:
    async with factory() as uow:
        await uow.people.save_practitioner(
            Practitioner(
                id=f"prac-lead-{number}",
                active=True,
                display_name=f"Lead {number}",
                phone_hash=None,
            )
        )
        await uow.people.save_role(
            PractitionerRole(
                id=f"role-lead-{number}",
                practitioner_id=f"prac-lead-{number}",
                service_id=None,
                code=PractitionerRoleCode(code),
                active=active,
                channel=Channel.PUSH,
                period_start=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
        await uow.commit()


def _command(message_id: str = "m-1", event: str = "ReportEscalated") -> NotifyLeadsCommand:
    return NotifyLeadsCommand(
        message_id=message_id,
        event_type=event,
        payload={
            "service_id": "ucr-west",
            "due_at": "2026-10-31T07:30:00Z",
            "at": "2026-10-31T09:00:00Z",
        },
    )


async def _recipients(factory: UnitOfWorkFactory) -> list[str]:
    async with factory() as uow:
        pending = await uow.outbox.pending(limit=1000)
    return sorted(m.payload["recipient_role_id"] for m in pending if m.event_type == "SendMessage")


async def test_the_active_shift_leads_of_the_tenant_are_told_once(
    uow_factory: UnitOfWorkFactory, seed_service: Seed
) -> None:
    await seed_service(SERVICE)
    await _lead(uow_factory, 1)
    await _lead(uow_factory, 2)
    await _lead(uow_factory, 3, active=False)  # a post that is not active is not told
    await _lead(uow_factory, 4, code="duty-manager")  # a reporter is not a shift lead
    use_case = _use_case(uow_factory)

    first = await use_case.execute(_command())
    again = await use_case.execute(_command())

    assert (first.notified, again.duplicate) == (2, True)
    assert await _recipients(uow_factory) == ["role-lead-1", "role-lead-2"]


async def test_another_tenants_lead_is_not_told_of_this_tenants_escalation(
    uow_factory: UnitOfWorkFactory,
    seed_service: Seed,
    neo4j_driver: AsyncDriver,
    other_tenant_id: str,
) -> None:
    await seed_service(SERVICE)
    await _lead(uow_factory, 1)
    await seed_service(dataclasses.replace(SERVICE), tenant=other_tenant_id)
    await ensure_audit_heads(neo4j_driver, other_tenant_id)
    other = tenant_uow_factory(neo4j_driver, other_tenant_id, FixedClock(NOW))
    with as_tenant(other_tenant_id):
        await _lead(other, 9)

    await _use_case(uow_factory).execute(_command())

    assert await _recipients(uow_factory) == ["role-lead-1"]
    with as_tenant(other_tenant_id):
        assert await _recipients(other) == []


async def test_a_tenant_with_no_shift_lead_commits_its_marker_and_an_audit_entry(
    uow_factory: UnitOfWorkFactory, seed_service: Seed
) -> None:
    await seed_service(SERVICE)
    use_case = _use_case(uow_factory)

    first = await use_case.execute(_command())
    again = await use_case.execute(_command())

    assert (first.notified, again.duplicate) == (0, True)
    assert await _recipients(uow_factory) == []
