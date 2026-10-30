"""Two-tenant test for booking replies by text (U22, DEC-130, DEC-131).

Tenant A has an open booking with reference R. Tenant B has its own reporter, on another phone
number, who replies CONFIRMED with R: the number called resolves to B, so B sees no open booking
and A's booking is not confirmed. Runs on contracted_container() (DEC-159, lesson L168).
"""

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from neo4j import AsyncDriver

from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.handle_inbound_text import HandleInboundTextCommand
from diucs.domain.codes import BookingStatus
from tests.integration.application.test_handle_inbound_text_booking import handler
from tests.support.booking_rig import (
    SERVICE_ID,
    at,
    open_case,
    request,
    seed_world,
)
from tests.support.ladder_rig import reporter, seed_people, seed_report
from tests.support.link_rig import ucr_west
from tests.support.neo4j import wipe_all
from tests.support.tenant_seed import contracted_container
from tests.support.uow import ensure_audit_heads, tenant_uow_factory

pytestmark = pytest.mark.asyncio(loop_scope="session")
PHONE_B = "de" * 32


@pytest_asyncio.fixture(loop_scope="session")
async def two_tenants(
    tenant_id: str, other_tenant_id: str
) -> AsyncIterator[tuple[AsyncDriver, UnitOfWorkFactory, UnitOfWorkFactory]]:
    async with contracted_container() as driver:
        await wipe_all(driver)
        await ensure_audit_heads(driver, tenant_id, other_tenant_id)
        factory_a = tenant_uow_factory(driver, tenant_id)
        factory_b = tenant_uow_factory(driver, other_tenant_id)
        await seed_world(factory_a, driver)
        async with factory_b() as uow:
            await uow.services.save(ucr_west(SERVICE_ID))
            await uow.cases.add(open_case())
            await uow.commit()
        await seed_people(factory_b, reporter(2, PHONE_B, service_id=SERVICE_ID))
        await seed_report(factory_b, at(13, 0), service_id=SERVICE_ID, value=4)
        yield driver, factory_a, factory_b


async def test_a_confirmed_text_in_tenant_b_cannot_confirm_tenant_as_booking_by_its_reference(
    two_tenants: tuple[AsyncDriver, UnitOfWorkFactory, UnitOfWorkFactory],
) -> None:
    driver, factory_a, factory_b = two_tenants
    booked = await request(factory_a, driver, "tt-u22-a")
    async with factory_a() as uow:
        booking = await uow.bookings.get(booked.booking_id)
    assert booking is not None
    reference = booking.reference
    result = await handler(factory_b, driver, at(14, 19), "tb22").execute(
        HandleInboundTextCommand(
            idempotency_key="tb22-1",
            from_phone_hash=PHONE_B,
            text=f"CONFIRMED {reference}",
            received_at=at(14, 19),
        )
    )
    assert result.outcome == "booking-none"
    async with factory_a() as uow:
        after = await uow.bookings.get(booked.booking_id)
    assert after is not None and after.status is BookingStatus.REQUESTED
