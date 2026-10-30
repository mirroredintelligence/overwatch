"""Two-tenant tests for the booking exceptions (U21, DEC-130 to DEC-132).

Tenant A and tenant B each hold a booking world with the same service id, case and reporter. A
confirmed booking of A is given to B's withdrawal and B's escalation timer: both read as not found,
and A's booking and its escalation are unchanged. Runs on contracted_container() (DEC-159, L168).
"""

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from neo4j import AsyncDriver

from diucs.adapters.outbound.graph_store.idempotency_store import DriverIdempotencyStore
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.withdraw_booking import (
    EscalateWithdrawal,
    EscalateWithdrawalCommand,
    WithdrawBooking,
    WithdrawBookingCommand,
)
from diucs.application.work import WorkKind
from diucs.domain.codes import BookingStatus, WithdrawReason
from diucs.domain.errors import NotFound
from tests.support.booking_rig import REPORTER, at, request, seed_world
from tests.support.neo4j import wipe_all
from tests.support.tenant_seed import contracted_container
from tests.support.uow import ensure_audit_heads, tenant_uow_factory

pytestmark = pytest.mark.asyncio(loop_scope="session")


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
        await seed_world(factory_b, driver)
        yield driver, factory_a, factory_b


async def test_tenant_b_cannot_withdraw_or_time_out_a_booking_and_a_is_unchanged(
    two_tenants: tuple[AsyncDriver, UnitOfWorkFactory, UnitOfWorkFactory],
) -> None:
    driver, factory_a, factory_b = two_tenants
    booked = await request(factory_a, driver, "tt-u21-a")
    await _confirm(factory_a, driver, booked.booking_id)
    withdraw_b = WithdrawBooking(
        factory_b, DriverIdempotencyStore(driver), FixedClock(at(14, 41)), SequentialIds("tb")
    )
    with pytest.raises(NotFound):
        await withdraw_b.execute(
            WithdrawBookingCommand(
                idempotency_key="tt-u21-b",
                actor=REPORTER,
                booking_id=booked.booking_id,
                reason=WithdrawReason.STAFFING,
            )
        )
    async with factory_a() as uow:
        booking = await uow.bookings.get(booked.booking_id)
        works = await uow.scheduled_work.for_about(booked.booking_id, WorkKind.WITHDRAWAL_ESCALATE)
    assert booking is not None and booking.status is BookingStatus.CONFIRMED
    assert works == []
    with pytest.raises(NotFound):
        await EscalateWithdrawal(factory_b, FixedClock(at(14, 51))).execute(
            EscalateWithdrawalCommand(work_id="no-such-work", booking_id=booked.booking_id)
        )


async def _confirm(factory: UnitOfWorkFactory, driver: AsyncDriver, booking_id: str) -> None:
    from diucs.application.use_cases.respond_to_booking import (
        RespondToBooking,
        RespondToBookingCommand,
    )
    from tests.support.booking_rig import sealer

    await RespondToBooking(
        factory,
        DriverIdempotencyStore(driver),
        FixedClock(at(14, 19)),
        SequentialIds("cf"),
        sealer(),
    ).execute(
        RespondToBookingCommand(
            idempotency_key=f"cf-{booking_id}",
            actor=REPORTER,
            booking_id=booking_id,
            decision="confirm",
        )
    )
