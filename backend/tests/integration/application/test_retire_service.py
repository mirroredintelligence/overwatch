"""Integration tests for RetireService (DEC-1356), against the real Neo4j.

UCR East has a report, a text reporter, two requested bookings with their timers and a prompt-due job
(the same world as the suspend tests). Retiring makes the service inactive, expires its requests and
cancels its prompt work; nothing is deleted.
"""

import pytest
from neo4j import AsyncDriver

from overwatch.adapters.testing.fixed_clock import FixedClock
from overwatch.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from overwatch.application.use_cases.retire_service import (
    RetireService,
    RetireServiceCommand,
    RetireServiceResult,
)
from overwatch.application.work import WorkKind
from overwatch.domain.codes import BookingStatus
from overwatch.domain.errors import Conflict, NotAllowed, NotFound
from tests.integration.application.test_suspend_service import EAST, seed_east, statuses
from tests.support.booking_rig import ADVISOR, LEAD, at
from tests.support.neo4j import count_nodes

pytestmark = pytest.mark.asyncio(loop_scope="session")


def retire(uow_factory: UnitOfWorkFactory) -> RetireService:
    return RetireService(uow_factory, FixedClock(at(14, 20)))


def command(key: str, *, actor=LEAD, service_id: str = EAST) -> RetireServiceCommand:  # type: ignore[no-untyped-def]
    return RetireServiceCommand(idempotency_key=key, actor=actor, service_id=service_id)


async def active_ids(uow_factory: UnitOfWorkFactory) -> list[str]:
    async with uow_factory() as uow:
        return [profile.id for profile in await uow.services.list_active()]


async def test_retiring_takes_the_service_off_every_active_list_and_expires_its_requests(
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    tenant_id: str,
    clean_graph: None,
) -> None:
    ids = await seed_east(uow_factory, neo4j_driver, tenant_id)
    assert EAST in await active_ids(uow_factory)
    result = await retire(uow_factory).execute(command("rt-1"))
    assert isinstance(result, RetireServiceResult)
    assert result.expired_requests == 2
    assert EAST not in await active_ids(uow_factory)
    assert await statuses(uow_factory, ids) == [BookingStatus.EXPIRED, BookingStatus.EXPIRED]
    async with uow_factory() as uow:
        prompt_work = await uow.scheduled_work.for_about(EAST, WorkKind.PROMPT_DUE)
        stored = await uow.services.get(EAST)
    assert [w.status for w in prompt_work] == ["cancelled"]
    assert stored is not None and stored.active is False  # kept, not deleted


async def test_retiring_again_is_a_conflict_and_the_same_key_replays(
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    tenant_id: str,
    clean_graph: None,
) -> None:
    await seed_east(uow_factory, neo4j_driver, tenant_id)
    first = await retire(uow_factory).execute(command("rt-2"))
    assert await retire(uow_factory).execute(command("rt-2")) == first
    with pytest.raises(Conflict):
        await retire(uow_factory).execute(command("rt-3"))


async def test_only_the_lead_retires_and_an_unknown_service_is_not_found(
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    tenant_id: str,
    clean_graph: None,
) -> None:
    await seed_east(uow_factory, neo4j_driver, tenant_id)
    with pytest.raises(NotAllowed):
        await retire(uow_factory).execute(command("rt-4", actor=ADVISOR))
    with pytest.raises(NotFound):
        await retire(uow_factory).execute(command("rt-5", service_id="no-such-service"))
    assert EAST in await active_ids(uow_factory)
    assert await count_nodes(neo4j_driver, "HealthcareService") >= 1
